import io
import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.api.routes.drone_intake import router
from lifejacket.config import settings
from lifejacket.models.db import get_session
from lifejacket.models.tables import AssignmentRow, Base, IncidentRow, ResponderRow
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def sessions():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    monkeypatch.setattr(settings, "drone_evidence_dir", tmp_path / "evidence")
    monkeypatch.setattr(settings, "drone_runs_dir", tmp_path / "runs")
    yield TestClient(app), factory


def upload(client, kind="real", **changes):
    metadata = dict(
        source_kind=kind,
        latitude=36.8,
        longitude=-121.8,
        observed_at=datetime.now(UTC).isoformat(),
        operator="Test coordinator",
        description="Test observation, evidence not medically assessed",
        area_terms=["Monterey County", "California"],
        animal_group="pinniped",
    )
    metadata.update(changes)
    image = io.BytesIO()
    Image.new("RGB", (10, 10)).save(image, format="JPEG")
    return client.post(
        "/drone-intake/observations",
        data={"metadata": json.dumps(metadata)},
        files={"photo": ("test.jpg", image.getvalue(), "image/jpeg")},
    )


def reviewed(client, kind="real"):
    row = upload(client, kind).json()
    path = f"/drone-intake/observations/{row['observation_id']}"
    response = client.post(
        path + "/review",
        json={
            "expected_revision": 0,
            "actor": "Coordinator",
            "decision": "verified",
            "note": "Reviewed image and metadata",
        },
    )
    assert response.status_code == 200, response.text
    return path, response.json()


def test_external_center_needs_no_app_registration_and_nothing_is_sent(api):
    client, factory = api
    path, row = reviewed(client)
    linked = client.post(path + "/case", json={"expected_revision": 1, "actor": "Coordinator"})
    assert linked.status_code == 200, linked.text
    incident_id = linked.json()["incident_id"]
    candidates = client.get(path + "/centers").json()
    assert candidates and candidates[0]["registration_required"] is False
    payload = {
        "expected_revision": 2,
        "actor": "Coordinator",
        "center_id": candidates[0]["center_id"],
        "coverage_and_capability_confirmed": True,
        "contact_details_confirmed": True,
        "verification_source": "https://www.fisheries.noaa.gov/report",
        "verification_note": "Test-only confirmation; no outreach",
    }
    draft = client.post(path + "/handoffs", json=payload)
    assert draft.status_code == 200, draft.text
    handoff = draft.json()
    assert handoff["outbound_message_sent"] is False
    assert "Species and medical severity are unconfirmed" in handoff["snapshot"]["packet_text"]
    with factory() as session:
        assert session.scalars(select(ResponderRow)).all() == []
        assert session.scalars(select(AssignmentRow)).all() == []
        assert session.get(IncidentRow, incident_id).status == "assessing"
    # A draft is not an acceptance; direct skipping is rejected.
    url = f"/drone-intake/handoffs/{handoff['handoff_id']}/status"
    body = {
        "expected_revision": 0,
        "actor": "Coordinator",
        "status": "accepted",
        "channel": "phone",
        "note": "Test-only status",
    }
    assert client.post(url, json=body).status_code == 409
    for revision, status in enumerate(["contact_attempted", "acknowledged", "accepted"]):
        body.update(expected_revision=revision, status=status)
        response = client.post(url, json=body)
        assert response.status_code == 200, response.text
    with factory() as session:
        assert session.get(IncidentRow, incident_id).assigned_responder_id is None
        assert session.scalars(select(AssignmentRow)).all() == []
    assert client.post(url, json=body).status_code == 409  # stale/repeated transition


def test_pending_and_simulated_evidence_cannot_create_live_case(api):
    client, factory = api
    pending = upload(client).json()
    path = f"/drone-intake/observations/{pending['observation_id']}"
    assert (
        client.post(path + "/case", json={"expected_revision": 0, "actor": "C"}).status_code
        == 409
    )
    sim_path, sim = reviewed(client, "simulation")
    assert (
        client.post(
            sim_path + "/case", json={"expected_revision": 1, "actor": "C"}
        ).status_code
        == 409
    )
    with factory() as session:
        assert session.scalars(select(IncidentRow)).all() == []


def test_review_is_versioned_and_upload_validates_image_and_time(api):
    client, _ = api
    path, row = reviewed(client)
    assert client.get(path + "/photo").headers["content-type"] == "image/jpeg"
    assert (
        client.post(
            path + "/review",
            json={
                "expected_revision": 0,
                "actor": "C",
                "decision": "rejected",
                "note": "stale",
            },
        ).status_code
        == 409
    )
    assert upload(client, observed_at="2026-10-22T10:00:00").status_code == 422
    metadata = row["metadata"]
    result = client.post(
        "/drone-intake/observations",
        data={"metadata": json.dumps(metadata)},
        files={"photo": ("fake.jpg", b"not an image", "image/jpeg")},
    )
    assert result.status_code == 422


def test_sitl_provenance_and_state_only_routing_are_not_live_matches(api):
    from lifejacket.drones.runs import save_run

    client, _ = api
    run_id = "a" * 32
    save_run(
        settings.drone_runs_dir, {"run_id": run_id, "synthetic": True, "status": "completed"}
    )
    assert upload(client, run_id=run_id).status_code == 409
    row = upload(client, area_terms=["California"]).json()
    path = f"/drone-intake/observations/{row['observation_id']}"
    assert client.get(path + "/centers").json() == []


def test_case_creation_is_idempotent_and_review_history_is_preserved(api):
    client, factory = api
    path, row = reviewed(client)
    rejected = client.post(
        path + "/review",
        json={
            "expected_revision": 1,
            "actor": "C",
            "decision": "rejected",
            "note": "Review correction",
        },
    ).json()
    assert len(rejected["review"]["history"]) == 2
    verified = client.post(
        path + "/review",
        json={
            "expected_revision": 2,
            "actor": "C",
            "decision": "verified",
            "note": "Correction resolved",
        },
    ).json()
    assert verified["revision"] == 3
    body = {"expected_revision": 3, "actor": "C"}
    first = client.post(path + "/case", json=body)
    second = client.post(path + "/case", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["incident_id"] == second.json()["incident_id"]
    with factory() as session:
        assert len(session.scalars(select(IncidentRow)).all()) == 1
    downloaded = client.get(path + "/photo?download=true")
    assert "attachment" in downloaded.headers["content-disposition"]
