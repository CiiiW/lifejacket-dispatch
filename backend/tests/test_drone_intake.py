import io
import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.api.routes.drone_intake import router
from lifejacket.config import settings
from lifejacket.llm.client import LLMCallError, get_client
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.models.db import get_session
from lifejacket.models.schemas import AnimalGroup
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


def vision_client(client, group="sea_turtle", *, animals=2):
    scripted = (
        ScriptedLLMClient()
        .queue(
            "detection",
            {
                "animals": [
                    {
                        "box": [100, 50 + i * 450, 800, 400 + i * 450],
                        "description": f"Animal on side {i + 1}",
                        "kind": "other",
                    }
                    for i in range(animals)
                ]
            },
        )
        .queue(
            "identification",
            {
                "candidates": [
                    {"common_name": "Test animal", "confidence": 0.96, "animal_group": group}
                ],
                "species_distinguishable": False,
            },
        )
        .queue(
            "assessment",
            {
                "injury_present": True,
                "injury_confidence": 0.6,
                "entanglement": True,
                "injury_summary": "Possible line around selected animal; needs expert review",
                "is_confident": False,
            },
        )
    )
    client.app.dependency_overrides[get_client] = lambda: scripted
    return scripted


def detection(client, row):
    path = f"/drone-intake/observations/{row['observation_id']}"
    result = client.post(
        path + "/detect", json={"expected_revision": row["revision"], "actor": "C"}
    )
    assert result.status_code == 200, result.text
    return path, result.json()


@pytest.mark.parametrize("group", list(AnimalGroup))
def test_drone_screening_reuses_every_chatbot_group_and_preserves_review_hold(api, group):
    from lifejacket.models import repository
    from lifejacket.services.events import incident_state

    client, factory = api
    scripted = vision_client(client, group.value)
    original = upload(client, animal_group=group.value).json()
    path, row = detection(client, original)
    assert row["status"] == "pending"
    result = client.post(
        path + "/analyze",
        json={
            "expected_revision": row["revision"],
            "actor": "C",
            "detection_id": row["analysis"]["analysis_id"],
            "animal_number": 2,
        },
    )
    assert result.status_code == 200, result.text
    row = result.json()
    assert row["analysis"]["identity_summary"]["animal_group"] == group.value
    assert row["analysis"]["animal_number"] == 2
    assert row["analysis"]["assessment"]["severity_level"] == "critical"
    assert row["analysis"]["assessment"]["requires_human_review"] is True
    assert row["sha256"] == original["sha256"]
    assert row["metadata"] == original["metadata"]
    assert [call.agent for call in scripted.calls] == [
        "detection",
        "identification",
        "assessment",
    ]
    assert f"Animal group: {group.value}" in scripted.calls[-1].prompt
    assert "Do not infer movement" in scripted.calls[-1].prompt
    assert (
        client.post(
            path + "/case", json={"expected_revision": row["revision"], "actor": "C"}
        ).status_code
        == 409
    )
    row = client.post(
        path + "/review",
        json={
            "expected_revision": row["revision"],
            "actor": "C",
            "decision": "verified",
            "note": "Reviewed selected animal and advisory findings",
        },
    ).json()
    assert row["review"]["analysis_id"] == row["analysis"]["analysis_id"]
    linked = client.post(
        path + "/case", json={"expected_revision": row["revision"], "actor": "C"}
    )
    assert linked.status_code == 200, linked.text
    with factory() as session:
        incident = repository.load_incident(session, linked.json()["incident_id"])
        assert incident.identification.animal_group == group
        assert incident.assessment.animal_group == group
        assert (
            incident_state(session.get(IncidentRow, incident.incident_id))[
                "requires_human_review"
            ]
            is True
        )
    if group in {AnimalGroup.TERRESTRIAL, AnimalGroup.DOMESTIC_ANIMAL}:
        assert client.get(path + "/centers").json() == []
    assert (
        client.post(
            path + "/detect",
            json={"expected_revision": linked.json()["revision"], "actor": "C"},
        ).status_code
        == 409
    )


def test_groups_come_from_shared_enum_and_analysis_requires_current_selected_animal(api):
    client, _ = api
    assert {item["value"] for item in client.get("/drone-intake/animal-groups").json()} == {
        g.value for g in AnimalGroup
    }
    scripted = vision_client(client)
    path, row = detection(client, upload(client).json())
    body = {
        "expected_revision": row["revision"],
        "actor": "C",
        "detection_id": row["analysis"]["analysis_id"],
        "animal_number": 3,
    }
    assert client.post(path + "/analyze", json=body).status_code == 409
    body.update(animal_number=1, detection_id=body["detection_id"] + 1)
    assert client.post(path + "/analyze", json=body).status_code == 409
    body.update(detection_id=row["analysis"]["analysis_id"], expected_revision=0)
    assert client.post(path + "/analyze", json=body).status_code == 409
    assert len(scripted.calls) == 1


def test_empty_detection_failure_and_reanalysis_do_not_bypass_review(api):
    client, _ = api
    scripted = vision_client(client, animals=0)
    path, reviewed_row = reviewed(client)
    path, row = detection(client, reviewed_row)
    assert row["analysis"]["detections"] == []
    assert row["status"] == "pending"
    assert (
        client.post(
            path + "/case", json={"expected_revision": row["revision"], "actor": "C"}
        ).status_code
        == 409
    )
    scripted.queue("detection", LLMCallError("test unavailable"))
    failed = client.post(
        path + "/detect", json={"expected_revision": row["revision"], "actor": "C"}
    )
    assert failed.status_code == 503
    saved = client.get("/drone-intake/observations").json()[0]
    assert saved["revision"] == row["revision"]
    assert saved["analysis"] == row["analysis"]
    assert client.get(path + "/photo").status_code == 200


def test_simulated_screening_never_creates_live_case(api):
    client, _ = api
    vision_client(client)
    path, row = detection(client, upload(client, "simulation").json())
    row = client.post(
        path + "/analyze",
        json={
            "expected_revision": row["revision"],
            "actor": "C",
            "animal_number": 1,
            "detection_id": row["analysis"]["analysis_id"],
        },
    ).json()
    assert row["analysis"]["source_kind"] == "simulation"
    row = client.post(
        path + "/review",
        json={
            "expected_revision": row["revision"],
            "actor": "C",
            "decision": "verified",
            "note": "Test only",
        },
    ).json()
    assert (
        client.post(
            path + "/case", json={"expected_revision": row["revision"], "actor": "C"}
        ).status_code
        == 409
    )


def test_identification_and_assessment_receive_selected_crop(api, monkeypatch):
    client, _ = api
    metadata = upload(client).json()["metadata"]
    photo = Image.new("RGB", (100, 100), "red")
    photo.paste("blue", (50, 0, 100, 100))
    data = io.BytesIO()
    photo.save(data, format="PNG")
    row = client.post(
        "/drone-intake/observations",
        data={"metadata": json.dumps(metadata)},
        files={"photo": ("selection.png", data.getvalue(), "image/png")},
    ).json()
    scripted = vision_client(client)
    original_generate = scripted.generate_json
    seen = []

    def capture(**kwargs):
        seen.append(Image.open(io.BytesIO(kwargs["images"][0].data)))
        return original_generate(**kwargs)

    monkeypatch.setattr(scripted, "generate_json", capture)
    path, row = detection(client, row)
    result = client.post(
        path + "/analyze",
        json={
            "expected_revision": row["revision"],
            "actor": "C",
            "animal_number": 2,
            "detection_id": row["analysis"]["analysis_id"],
        },
    )
    assert result.status_code == 200, result.text
    assert seen[0].size == (100, 100)
    for crop in seen[1:]:
        assert crop.size == (42, 84)
        red, green, blue = crop.getpixel((21, 42))
        assert blue > 240 and red < 15 and green < 15


def test_changed_evidence_fails_before_calling_model(api):
    from pathlib import Path

    from lifejacket.models.tables import DroneObservationRow

    client, factory = api
    row = upload(client).json()
    with factory() as session:
        stored = session.get(DroneObservationRow, row["observation_id"])
        Path(stored.storage_path).write_bytes(b"changed evidence")
    scripted = vision_client(client)
    path = f"/drone-intake/observations/{row['observation_id']}"
    assert (
        client.post(
            path + "/detect", json={"expected_revision": row["revision"], "actor": "C"}
        ).status_code
        == 422
    )
    assert scripted.calls == []
