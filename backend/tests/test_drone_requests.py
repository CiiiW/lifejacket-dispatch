"""Exercise real network routes with disposable data and synthetic identity only."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from lifejacket.access.policy import Role
from lifejacket.api.routes import drone_requests
from lifejacket.config import settings
from lifejacket.models.tables import (
    CaseDroneEventRow,
    CaseDroneEvidenceRow,
    IncidentRow,
    NetworkCaseRow,
)
from PIL import Image
from sqlalchemy import select
from test_network_actions import actor, api  # noqa: F401

BASE = "/network/cases/case/drone-requests"


@pytest.fixture
def drone_api(api, monkeypatch, tmp_path):  # noqa: F811
    client, factory, current = api
    client.app.include_router(drone_requests.router)
    monkeypatch.setattr(settings, "case_drone_requests_enabled", True)
    monkeypatch.setattr(settings, "drone_evidence_dir", tmp_path / "evidence")
    return client, factory, current


def payload(**extra):
    return dict(
        purpose="verification",
        objective="Can the animal move?",
        reason="Reporter view is obstructed",
        execution_kind="recorded_demo",
        escalation_criteria="New evidence of distress",
        request_key="one",
        **extra,
    )


def create(client, **extra):
    r = client.post(BASE, json=payload(**extra))
    assert r.status_code == 201, r.text
    return r.json()


def change(client, row, status, **extra):
    return client.patch(
        BASE + "/" + row["request_id"],
        json={
            "revision": row["revision"],
            "status": status,
            "confirmed": True,
            "note": "Reviewed fictional test evidence",
            **extra,
        },
    )


def start(client):
    row = create(client)
    r = change(client, row, "approved", operator="Demo reviewer")
    assert r.status_code == 200, r.text
    r = change(client, r.json(), "in_progress")
    assert r.status_code == 200, r.text
    return r.json()


def upload(client, row, **extra):
    b = io.BytesIO()
    Image.new("RGB", (12, 12), "blue").save(b, format="PNG")
    import json

    meta = dict(
        revision=row["revision"],
        source_kind="sample_footage",
        source_url="https://www.fisheries.noaa.gov/example-video",
        rights_note="Synthetic test image, no NOAA media used",
        description="Fictional demo frame",
    )
    meta.update(extra)
    return client.post(
        BASE + "/" + row["request_id"] + "/evidence",
        data={"metadata": json.dumps(meta)},
        files={"photo": ("frame.png", b.getvalue(), "image/png")},
    )


def test_full_demo_preserves_intake_and_audits_every_change(drone_api):
    client, factory, _ = drone_api
    row = start(client)
    response = upload(client, row)
    assert response.status_code == 201, response.text
    row["revision"] = response.json()["revision"]
    ready = change(client, row, "evidence_ready")
    assert ready.status_code == 200, ready.text
    reviewed = change(client, ready.json(), "reviewed", outcome="still_uncertain")
    assert reviewed.status_code == 200, reviewed.text
    detail = client.get(BASE + "/" + row["request_id"])
    assert detail.status_code == 200 and "no-store" in detail.headers["cache-control"]
    value = detail.json()
    assert value["outcome"] == "still_uncertain"
    assert value["evidence"][0]["captured_at"] is None
    assert value["evidence"][0]["animal_latitude"] is None
    assert [e["kind"] for e in value["events"]] == [
        "requested",
        "approved",
        "in_progress",
        "evidence_attached",
        "evidence_ready",
        "reviewed",
    ]
    eid = value["evidence"][0]["evidence_id"]
    assert (
        client.get(BASE + "/" + row["request_id"] + "/evidence/" + eid + "/photo").status_code
        == 200
    )
    with factory() as session:
        assert session.get(IncidentRow, "case").report_json == {"secret": "INTERNAL"}
        assert session.get(NetworkCaseRow, "case").response_phase == "received"
        assert len(session.scalars(select(CaseDroneEventRow)).all()) == 6
        assert len(session.scalars(select(CaseDroneEvidenceRow)).all()) == 1


@pytest.mark.parametrize(
    "person",
    [
        actor("C"),
        actor("N", Role.NOAA, states=()),
        actor("B"),
        actor("B", Role.RESCUER, "rescuer"),
        actor("A", Role.REPORTER),
        actor("A", states=("AK",)),
    ],
)
def test_read_scope_never_grants_write_permission(drone_api, person):
    client, _, current = drone_api
    row = create(client)
    current[0] = person
    assert client.post(BASE, json=payload()).status_code in {403, 404}
    assert change(client, row, "approved", operator="x").status_code in {403, 404}
    if person.organization_id in {"C", "N"}:
        assert client.get(BASE).status_code in {403, 404}


def test_monitoring_time_idempotency_and_stale_writes(drone_api):
    client, _, _ = drone_api
    body = payload()
    body["purpose"] = "monitoring"
    assert client.post(BASE, json=body).status_code == 422
    body["next_review_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = client.post(BASE, json=body)
    assert response.status_code == 201, response.text
    row = response.json()
    assert client.post(BASE, json=body).json()["request_id"] == row["request_id"]
    body["objective"] = "Changed"
    assert client.post(BASE, json=body).status_code == 409
    assert change(client, row, "evidence_ready").status_code == 409
    assert change(client, row, "approved").status_code == 422
    assert change(client, row, "approved", operator="Operator").status_code == 200
    assert change(client, row, "approved", operator="Operator").status_code == 409


def test_evidence_and_review_guards(drone_api):
    client, _, _ = drone_api
    row = start(client)
    assert change(client, row, "evidence_ready").status_code == 409
    assert upload(client, row, source_kind="operator_capture").status_code == 422
    result = upload(client, row)
    assert result.status_code == 201
    assert upload(client, row).status_code == 409
    row["revision"] = result.json()["revision"]
    ready = change(client, row, "evidence_ready").json()
    assert change(client, ready, "reviewed").status_code == 422
    assert change(client, ready, "reviewed", outcome="escalation_needed").status_code == 200
    assert upload(client, ready).status_code == 409


def test_feature_off_closed_case_and_cross_case_ids(drone_api, monkeypatch):
    client, factory, _ = drone_api
    row = create(client)
    assert (
        client.get("/network/cases/missing/drone-requests/" + row["request_id"]).status_code
        == 404
    )
    with factory() as session:
        session.get(NetworkCaseRow, "case").response_phase = "closed"
        session.commit()
    assert change(client, row, "approved", operator="x").status_code == 403
    monkeypatch.setattr(settings, "case_drone_requests_enabled", False)
    assert client.get(BASE).status_code == 503
    assert client.post(BASE, json=payload()).status_code == 403


def test_operator_flight_requires_feasibility_and_real_capture_metadata(drone_api):
    client, _, _ = drone_api
    body = payload()
    body["execution_kind"] = "operator_flight"
    row = client.post(BASE, json=body).json()
    approved = change(client, row, "approved", operator="Mini 2 operator").json()
    assert change(client, approved, "in_progress").status_code == 422
    running = change(client, approved, "in_progress", feasibility_confirmed=True)
    assert running.status_code == 200
    assert upload(client, running.json()).status_code == 422


def test_anonymous_and_revoked_participation_cannot_read_evidence(drone_api):
    from lifejacket.access.dependencies import current_access_session

    client, factory, current = drone_api
    row = start(client)
    assert upload(client, row).status_code == 201
    current[0] = actor("C")
    assert client.get(BASE + "/" + row["request_id"]).status_code == 403
    client.app.dependency_overrides.pop(current_access_session)
    assert client.get(BASE).status_code == 401


def test_metadata_image_and_terminal_state_validation(drone_api):
    import json

    client, _, _ = drone_api
    row = start(client)
    assert upload(client, row, source_url="javascript:alert(1)").status_code == 422
    assert (
        upload(
            client, row, captured_at=(datetime.now(UTC) + timedelta(days=1)).isoformat()
        ).status_code
        == 422
    )
    assert upload(client, row, animal_latitude=36.8).status_code == 422
    response = client.post(
        BASE + "/" + row["request_id"] + "/evidence",
        data={
            "metadata": json.dumps(
                {
                    "revision": row["revision"],
                    "source_kind": "sample_footage",
                    "source_url": "https://www.fisheries.noaa.gov/",
                    "rights_note": "test",
                    "description": "not an image",
                }
            )
        },
        files={"photo": ("fake.png", b"not an image", "image/png")},
    )
    assert response.status_code == 422
    assert change(client, row, "cancelled").status_code == 200
    assert change(client, row, "approved", operator="x").status_code == 409
