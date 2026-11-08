"""Persistent analysis and reminders use synthetic cases, identities and transport."""

# ruff: noqa: F811
import hashlib
import hmac
import io
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from lifejacket.access.policy import Role
from lifejacket.api.routes import drone_followup
from lifejacket.config import settings
from lifejacket.models.tables import (
    AccessMembershipRow,
    AccessOrganizationRow,
    AccessUserRow,
    CaseDroneAnalysisRow,
    CaseDroneEvidenceRow,
    CaseDroneReminderRow,
    CaseDroneRequestRow,
    IncidentRow,
    NetworkCaseRow,
)
from lifejacket.services import (
    drone_frame_analysis as ai,
)
from lifejacket.services import (
    drone_reminders as reminders,
)
from lifejacket.services import (
    drone_requests as requests,
)
from PIL import Image
from sqlalchemy import select
from test_drone_requests import BASE, drone_api, start, upload  # noqa: F401
from test_network_actions import actor, api  # noqa: F401


@pytest.fixture
def followup_api(drone_api, monkeypatch):
    client, factory, current = drone_api
    client.app.include_router(drone_followup.router)
    monkeypatch.setattr(settings, "drone_frame_analysis_enabled", True)
    monkeypatch.setattr(settings, "drone_reminders_enabled", True)
    monkeypatch.setattr(
        settings, "drone_reminder_webhooks", {"A": "https://example.invalid/synthetic-inbox"}
    )
    monkeypatch.setattr(settings, "drone_reminder_signing_keys", {"A": "k" * 40})
    with factory() as db:
        db.add(AccessUserRow(user_id="staff", issuer="fixture", subject="staff", enabled=True))
        db.add(
            AccessOrganizationRow(
                organization_id="A",
                name="Synthetic Center A",
                kind="rescue_center",
                enabled=True,
                approved_states=["CA"],
                verified_at=requests.now(),
                verified_by="fixture-reviewer",
            )
        )
        db.add(
            AccessMembershipRow(
                membership_id="memberA",
                user_id="staff",
                organization_id="A",
                role="center_coordinator",
                status="active",
                approved_states=["CA"],
                verified_at=requests.now(),
                verified_by="fixture-reviewer",
            )
        )
        db.commit()
    return client, factory, current


def evidence(client):
    row = start(client)
    attached = upload(client, row)
    assert attached.status_code == 201, attached.text
    row["revision"] = attached.json()["revision"]
    return row, attached.json()["evidence_id"]


def queue(client, row, eid, **extra):
    body = {
        "revision": row["revision"],
        "confirmed": True,
        "stage": "detect",
        "request_key": "detect-one",
        **extra,
    }
    return client.post(
        BASE + "/" + row["request_id"] + "/evidence/" + eid + "/analysis", json=body
    )


def detect_result():
    return {
        "detections": [
            {
                "box": [0, 0, 1000, 500],
                "description": "Left synthetic target",
                "kind": "other",
            },
            {
                "box": [0, 500, 1000, 1000],
                "description": "Right synthetic target",
                "kind": "other",
            },
        ],
        "model": "fixture",
        "limitations": ["Synthetic result; no wildlife validation"],
    }


def test_queued_detection_is_idempotent_and_never_changes_intake(followup_api):
    client, factory, _ = followup_api
    row, eid = evidence(client)
    r = queue(client, row, eid)
    assert r.status_code == 202, r.text
    same = queue(client, row, eid)
    assert same.status_code == 202
    assert same.json()["analysis_id"] == r.json()["analysis_id"]
    calls = []
    assert ai.process_one(
        factory, lambda db, job: calls.append(job.evidence_id) or detect_result()
    )
    assert calls == [eid]
    assert not ai.process_one(factory, lambda *_: pytest.fail("Completed job ran twice"))
    result = client.get(BASE + "/" + row["request_id"] + "/analysis")
    assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
    job = result.json()["jobs"][0]
    assert job["status"] == "completed"
    assert "lease_token" not in result.text and "storage_path" not in result.text
    with factory() as db:
        assert db.get(IncidentRow, "case").report_json == {"secret": "INTERNAL"}
        assert db.get(NetworkCaseRow, "case").response_phase == "received"


def test_selected_animal_uses_correct_crop_and_unknown_capture_time(followup_api, monkeypatch):
    client, factory, _ = followup_api
    row, eid = evidence(client)
    queued = queue(client, row, eid).json()
    row["revision"] = queued["revision"]
    assert ai.process_one(factory, lambda *_: detect_result())
    selected = queue(
        client,
        row,
        eid,
        stage="assess",
        request_key="assess-two",
        detection_job_id=queued["analysis_id"],
        animal_index=1,
    )
    assert selected.status_code == 202, selected.text
    seen = []

    def analyze(image, number, **kwargs):
        with Image.open(io.BytesIO(image.data)) as picture:
            assert picture.width < 12
        seen.append((number, kwargs))
        return {
            "identity_summary": {"name": "Synthetic target", "confidence": 0.5},
            "assessment": {"requires_human_review": True},
            "limitations": ["Fixture only"],
        }

    monkeypatch.setattr(ai, "analyze_still", analyze)
    assert ai.process_one(factory)
    assert seen == [(2, {"client": None, "viewpoint": "unknown", "observed_at": None})]
    with factory() as db:
        assert db.get(IncidentRow, "case").assessment_json is None
        assert (
            db.get(CaseDroneAnalysisRow, selected.json()["analysis_id"]).status == "completed"
        )


@pytest.mark.parametrize("change", ["membership", "user", "lead", "scope"])
def test_revocation_before_execution_cancels_without_model_call(followup_api, change):
    client, factory, _ = followup_api
    row, eid = evidence(client)
    job = queue(client, row, eid).json()
    with factory() as db:
        if change == "membership":
            db.get(AccessMembershipRow, "memberA").status = "revoked"
        if change == "user":
            db.get(AccessUserRow, "staff").enabled = False
        if change == "lead":
            db.get(NetworkCaseRow, "case").lead_org_id = "B"
        if change == "scope":
            db.get(NetworkCaseRow, "case").verified_at = None
        db.commit()
    assert ai.process_one(factory, lambda *_: pytest.fail("Revoked job called the model"))
    with factory() as db:
        assert db.get(CaseDroneAnalysisRow, job["analysis_id"]).status == "cancelled"


def test_permission_changed_during_inference_discards_result(followup_api):
    client, factory, _ = followup_api
    row, eid = evidence(client)
    job = queue(client, row, eid).json()

    def inference(db, _):
        with factory() as changed:
            changed.get(AccessMembershipRow, "memberA").status = "revoked"
            changed.commit()
        return detect_result()

    assert ai.process_one(factory, inference)
    with factory() as db:
        saved = db.get(CaseDroneAnalysisRow, job["analysis_id"])
        assert saved.status == "cancelled" and saved.result_json is None


def test_integrity_failure_is_sanitized_and_retry_is_explicit(followup_api):
    client, factory, _ = followup_api
    row, eid = evidence(client)
    job = queue(client, row, eid).json()
    with factory() as db:
        image = db.get(CaseDroneEvidenceRow, eid)
        Path(image.storage_path).write_bytes(b"corrupt")
    assert ai.process_one(factory)
    detail = client.get(BASE + "/" + row["request_id"] + "/analysis").json()["jobs"][0]
    assert detail["status"] == "failed" and detail["error_code"] == "analysis_failed"
    assert "storage_path" not in json.dumps(detail)
    row["revision"] = job["revision"]
    retry = queue(client, row, eid)
    assert retry.status_code == 202 and retry.json()["analysis_id"] == job["analysis_id"]
    assert retry.json()["status"] == "queued"


def test_selection_scope_confirmation_and_nonlead_access(followup_api):
    client, _, current = followup_api
    row, eid = evidence(client)
    assert queue(client, row, eid, confirmed=False).status_code == 422
    assert queue(client, row, "0" * 32).status_code == 404
    assert (
        queue(
            client, row, eid, stage="assess", detection_job_id="0" * 32, animal_index=0
        ).status_code
        == 409
    )
    current[0] = actor("B", Role.RESCUER, "rescuer")
    assert queue(client, row, eid).status_code == 403
    current[0] = actor("C")
    assert client.get(BASE + "/" + row["request_id"] + "/analysis").status_code in {403, 404}


def overdue(client, factory):
    row = start(client)
    with factory() as db:
        saved = db.get(CaseDroneRequestRow, row["request_id"])
        saved.payload_json = {
            **saved.payload_json,
            "next_review_at": (requests.now() - timedelta(hours=1)).isoformat() + "Z",
        }
        db.commit()
    return row


def test_background_reminder_delivers_once_signed_without_open_browser(followup_api):
    client, factory, _ = followup_api
    row = overdue(client, factory)
    sent = []
    assert reminders.deliver_one(
        factory, lambda url, body, headers: sent.append((url, body, headers))
    )
    assert not reminders.deliver_one(factory, lambda *_: pytest.fail("Duplicate reminder"))
    assert len(sent) == 1
    _, body, headers = sent[0]
    payload = json.loads(body)
    assert payload["organization_id"] == "A" and payload["case_id"] == "case"
    assert (
        "INTERNAL" not in body.decode()
        and "latitude" not in payload
        and "objective" not in payload
    )
    assert headers["Idempotency-Key"] == payload["notification_id"]
    assert (
        headers["X-LifeJacket-Signature"]
        == "sha256=" + hmac.new(b"k" * 40, body, hashlib.sha256).hexdigest()
    )
    status = client.get(BASE + "/" + row["request_id"] + "/reminders")
    assert status.status_code == 200 and status.json()["items"][0]["status"] == "delivered"
    assert "example.invalid" not in status.text and "kkkk" not in status.text
    with factory() as db:
        assert not db.get(CaseDroneRequestRow, row["request_id"]).payload_json.get(
            "attention_acknowledgments"
        )


def test_delivery_retries_keep_same_id_and_body(followup_api):
    client, factory, _ = followup_api
    overdue(client, factory)
    calls = []

    def fail(url, body, headers):
        calls.append((body, headers))
        raise OSError("SECRET PROVIDER DIAGNOSTIC")

    assert reminders.deliver_one(factory, fail)
    with factory() as db:
        item = db.scalar(select(CaseDroneReminderRow))
        assert item.status == "queued" and item.error_code == "delivery_failed"
        item.next_attempt_at = requests.now()
        db.commit()
    assert reminders.deliver_one(
        factory, lambda url, body, headers: calls.append((body, headers))
    )
    assert calls[0] == calls[1]


@pytest.mark.parametrize("change", ["closed", "lead", "ack", "verification"])
def test_changed_attention_cancels_unsent_delivery(followup_api, change):
    client, factory, _ = followup_api
    row = overdue(client, factory)
    with factory() as db:
        reminders.scan(db)
        item = db.scalar(select(CaseDroneReminderRow))
        if change == "closed":
            db.get(NetworkCaseRow, "case").response_phase = "closed"
        if change == "lead":
            db.get(NetworkCaseRow, "case").lead_org_id = "B"
        if change == "verification":
            db.get(NetworkCaseRow, "case").verified_at = None
        if change == "ack":
            request = db.get(CaseDroneRequestRow, row["request_id"])
            request.payload_json = {
                **request.payload_json,
                "attention_acknowledgments": {
                    item.attention_key: {"acknowledged_at": "fixture"}
                },
            }
        db.commit()
    assert not reminders.deliver_one(factory, lambda *_: pytest.fail("Ineligible delivery"))
    with factory() as db:
        assert db.scalar(select(CaseDroneReminderRow)).status == "cancelled"


def test_unconfigured_delivery_blocks_then_recovers(followup_api, monkeypatch):
    client, factory, _ = followup_api
    overdue(client, factory)
    monkeypatch.setattr(settings, "drone_reminder_webhooks", {})
    assert not reminders.deliver_one(
        factory, lambda *_: pytest.fail("Unconfigured outbound call")
    )
    with factory() as db:
        assert db.scalar(select(CaseDroneReminderRow)).status == "blocked"
    monkeypatch.setattr(
        settings, "drone_reminder_webhooks", {"A": "https://example.invalid/fixture"}
    )
    assert reminders.deliver_one(factory, lambda *_: None)


def test_failure_limit_and_coordinator_retry(followup_api):
    client, factory, _ = followup_api
    row = overdue(client, factory)
    with factory() as db:
        reminders.scan(db)
        item = db.scalar(select(CaseDroneReminderRow))
        item.attempts = 4
        db.commit()

    def failure(*_):
        raise OSError("provider unavailable")

    assert reminders.deliver_one(factory, failure)
    with factory() as db:
        item = db.scalar(select(CaseDroneReminderRow))
        assert item.status == "failed"
        nid = item.notification_id
    retry = client.post(
        BASE + "/" + row["request_id"] + "/reminders/retry",
        json={"revision": row["revision"], "confirmed": True, "notification_id": nid},
    )
    assert retry.status_code == 200, retry.text
    assert reminders.deliver_one(factory, lambda *_: None)


def test_detection_agent_receives_only_integrity_checked_saved_frame(
    followup_api, monkeypatch
):
    client, factory, _ = followup_api
    row, eid = evidence(client)
    queued = queue(client, row, eid).json()
    seen = []

    class Detector:
        def __init__(self, client):
            self.client = SimpleNamespace(model="fixture")
            self.last_metrics = {}

        def run(self, *, images):
            seen.append(images[0])
            return SimpleNamespace(
                model_dump=lambda **_: {"animals": detect_result()["detections"]}
            )

    monkeypatch.setattr(ai, "DetectionAgent", Detector)
    assert ai.process_one(factory)
    with factory() as db:
        image = db.get(CaseDroneEvidenceRow, eid)
        assert hashlib.sha256(seen[0].data).hexdigest() == image.sha256
        job = db.get(CaseDroneAnalysisRow, queued["analysis_id"])
        assert job.status == "completed" and len(job.result_json["detections"]) == 2


def test_atomic_lease_and_old_worker_cannot_overwrite_new_result(followup_api):
    from lifejacket.services import drone_followup as common

    client, factory, _ = followup_api
    row, eid = evidence(client)
    queued = queue(client, row, eid).json()
    with factory() as first, factory() as second:
        one = first.get(CaseDroneAnalysisRow, queued["analysis_id"])
        two = second.get(CaseDroneAnalysisRow, queued["analysis_id"])
        token = common.claim(first, CaseDroneAnalysisRow, one)
        assert token and common.claim(second, CaseDroneAnalysisRow, two) is None
        first.refresh(one)
        one.next_attempt_at = requests.now() - timedelta(seconds=1)
        first.commit()
        assert ai.process_one(factory, lambda *_: detect_result())
        common.finish(
            first, CaseDroneAnalysisRow, one, token, "failed", error_code="old_worker"
        )
        first.refresh(one)
        assert one.status == "completed" and one.error_code is None


def test_worker_commands_persist_attention_without_browser_or_delivery(followup_api):
    import os
    import subprocess
    import sys

    from lifejacket.models.tables import DroneWorkerHeartbeatRow

    client, factory, _ = followup_api
    overdue(client, factory)
    root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "DATABASE_URL": str(factory.kw["bind"].url),
        "NETWORK_AUTH_ENABLED": "true",
        "CASE_DRONE_REQUESTS_ENABLED": "true",
        "DRONE_FRAME_ANALYSIS_ENABLED": "true",
        "DRONE_REMINDERS_ENABLED": "true",
        "DRONE_REMINDER_WEBHOOKS": "{}",
        "DRONE_REMINDER_SIGNING_KEYS": "{}",
    }
    for kind in ["analysis", "reminders"]:
        result = subprocess.run(
            [
                sys.executable,
                str(root / "scripts/drone_followup_worker.py"),
                "--kind",
                kind,
                "--once",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, "Worker command failed"
    with factory() as db:
        assert db.get(DroneWorkerHeartbeatRow, "analysis") is not None
        assert db.get(DroneWorkerHeartbeatRow, "reminders") is not None
        assert db.scalar(select(CaseDroneReminderRow)).status == "blocked"


def test_concurrent_first_worker_heartbeats(followup_api):
    from concurrent.futures import ThreadPoolExecutor

    from lifejacket.models.tables import DroneWorkerHeartbeatRow
    from lifejacket.services import drone_followup as common

    _, factory, _ = followup_api

    def beat(_):
        with factory() as db:
            common.heartbeat(db, "analysis")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(beat, range(12)))
    with factory() as db:
        rows = list(db.scalars(select(DroneWorkerHeartbeatRow)))
        assert len(rows) == 1
        assert rows[0].worker_kind == "analysis"


def test_once_worker_failure_is_nonzero_and_redacted(followup_api, monkeypatch, capsys):
    import importlib.util
    import sys
    from pathlib import Path

    _, factory, _ = followup_api
    path = Path(__file__).resolve().parents[2] / "scripts/drone_followup_worker.py"
    spec = importlib.util.spec_from_file_location("live_worker_failure_test", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "init_db", lambda: None)
    monkeypatch.setattr(worker.signal, "signal", lambda *args: None)

    def fail(_):
        raise RuntimeError("SECRET_PROVIDER_PAYLOAD")

    monkeypatch.setattr(worker.ai, "process_one", fail)
    monkeypatch.setattr(sys, "argv", ["worker", "--kind", "analysis", "--once"])
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 1
    logged = capsys.readouterr().err
    assert "RuntimeError" in logged
    assert "SECRET_PROVIDER_PAYLOAD" not in logged
