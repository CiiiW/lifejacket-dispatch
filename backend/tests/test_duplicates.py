"""Duplicate reports, through the database and over HTTP.

`test_dispatch.py` covers the scoring maths. These tests cover the two rules
about *what a duplicate is allowed to cancel*:

1. Only an incident someone is actively handling can be a duplicate target.
2. Reports that disagree on the animal group are flagged, never suppressed.

Both exist because the costly error here is not a second team at one animal;
it is a real animal whose report was cancelled against the wrong thing.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.config import settings
from lifejacket.dispatch.duplicates import ACTIVE_DUPLICATE_TARGET_STATUSES
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.models import repository
from lifejacket.models.db import get_session
from lifejacket.models.schemas import EnvironmentalContext, IncidentStatus
from lifejacket.models.tables import Base, IncidentRow
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BEACH = {"latitude": 36.8000, "longitude": -121.7900}


@pytest.fixture
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Which earlier incidents a new report may be matched against
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(IncidentStatus))
def test_only_actively_handled_incidents_are_duplicate_targets(database, status):
    with database() as session:
        session.add(
            IncidentRow(
                incident_id="INC_earlier",
                status=status.value,
                created_at=datetime.now() - timedelta(minutes=30),
                latitude=BEACH["latitude"],
                longitude=BEACH["longitude"],
                animal_group="pinniped",
            )
        )
        session.commit()

        candidates = repository.find_duplicate_candidates(
            session, incident_id="INC_new", **BEACH
        )

    found = [c.incident_id for c in candidates]
    if status in ACTIVE_DUPLICATE_TARGET_STATUSES:
        assert found == ["INC_earlier"]
    else:
        assert found == [], (
            f"a new report must not be cancelled against a {status.value} incident"
        )


def test_ended_and_unfinished_statuses_are_the_ones_excluded():
    """Spelled out, so adding a status forces a decision about which side it is on."""
    excluded = set(IncidentStatus) - ACTIVE_DUPLICATE_TARGET_STATUSES
    assert excluded == {
        IncidentStatus.INTAKE,
        IncidentStatus.IDENTIFYING,
        IncidentStatus.ASSESSING,
        IncidentStatus.RESOLVED,
        IncidentStatus.CANCELLED,
        IncidentStatus.GUIDANCE_ONLY,
    }


# ---------------------------------------------------------------------------
# Whole reports over HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def api(database, tmp_path, monkeypatch):
    def session_override():
        session = database()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(settings, "photo_storage_dir", tmp_path / "photos")
    monkeypatch.setattr(
        "lifejacket.services.pipeline.gather_context",
        lambda location: EnvironmentalContext(location=location, unavailable=["tide"]),
    )
    monkeypatch.setattr("lifejacket.services.pipeline.reverse_geocode", lambda *a: None)

    # Each report gets a fresh script, so two reports can be different animals.
    current: dict[str, ScriptedLLMClient] = {}
    monkeypatch.setattr("lifejacket.agents.base.get_client", lambda: current["client"])

    def start(scenario: str, location: dict = BEACH) -> tuple[str, dict]:
        """Open a report as far as photo and location. Returns its id and the turn."""
        current["client"] = ScriptedLLMClient.scenario(scenario)
        client = TestClient(app)
        incident_id = client.post("/intake/start", json={}).json()["incident_id"]
        client.post(
            f"/intake/{incident_id}/photo",
            files={"file": ("animal.jpg", b"\xff\xd8\xff fake jpeg", "image/jpeg")},
        )
        turn = client.post(f"/intake/{incident_id}/location", json=location).json()
        return incident_id, turn

    def report(scenario: str, answers: list[str], location: dict = BEACH) -> str:
        """File one complete report and return its incident id."""
        incident_id, turn = start(scenario, location)
        client = TestClient(app)
        for answer in answers:
            assert not turn["complete"], "scenario finished before all answers were used"
            turn = client.post(f"/intake/{incident_id}/reply", json={"text": answer}).json()
        assert turn["complete"], f"scenario '{scenario}' needs more answers"
        return incident_id

    report.start = start
    yield TestClient(app), report
    app.dependency_overrides.clear()


SEA_LION = ("sea_lion", ["yes, green netting"])
DOLPHIN = ("dolphin", ["long beak", "yes"])


def test_second_report_of_the_same_animal_is_still_linked_and_suppressed(api):
    """The behaviour that existed before, unchanged: one animal, one dispatch."""
    client, report = api
    first = report(*SEA_LION)
    second = report(*SEA_LION)

    detail = client.get(f"/incidents/{second}").json()
    assert detail["status"] == "cancelled"
    assert detail["duplicate_of"] == first
    assert detail["possible_duplicate"] is None


def test_different_animal_on_the_same_beach_is_dispatched_and_flagged(api):
    client, report = api
    sea_lion = report(*SEA_LION)
    dolphin = report(*DOLPHIN)

    detail = client.get(f"/incidents/{dolphin}").json()
    assert detail["status"] == "awaiting_dispatch"  # not cancelled
    assert detail["duplicate_of"] is None
    assert detail["dispatch_candidates"] is not None

    flagged = detail["possible_duplicate"]
    assert flagged["incident_id"] == sea_lion
    assert flagged["same_species"] is False
    assert "different animal group" in flagged["reason"]


def test_new_report_after_the_first_case_ended_gets_its_own_response(api):
    client, report = api
    first = report(*SEA_LION)
    client.patch(f"/incidents/{first}/status", json={"status": "resolved"})

    second = report(*SEA_LION)

    detail = client.get(f"/incidents/{second}").json()
    assert detail["status"] == "awaiting_dispatch"
    assert detail["duplicate_of"] is None
    assert detail["possible_duplicate"] is None  # nothing active to compare against


def test_unfinished_intake_nearby_does_not_cancel_a_complete_report(api):
    """Someone starts a report at the same spot and walks away mid-conversation."""
    client, report = api
    abandoned, turn = report.start("sea_lion")
    assert not turn["complete"]  # a question is waiting that nobody will answer

    complete = report(*SEA_LION)

    detail = client.get(f"/incidents/{complete}").json()
    assert detail["status"] == "awaiting_dispatch"
    assert detail["duplicate_of"] is None
    assert detail["possible_duplicate"] is None
    assert client.get(f"/incidents/{abandoned}").json()["status"] not in (
        "awaiting_dispatch",
        "cancelled",
    )


def test_weak_match_is_recorded_but_not_shown_to_the_coordinator(api, database):
    """~900 m along the beach: inside the window, well under the threshold."""
    client, report = api
    report(*SEA_LION)
    further = report(*SEA_LION, location={"latitude": 36.8081, "longitude": -121.7900})

    detail = client.get(f"/incidents/{further}").json()
    assert detail["status"] == "awaiting_dispatch"
    assert detail["duplicate_of"] is None
    assert detail["possible_duplicate"] is None

    with database() as session:
        recorded = session.get(IncidentRow, further).metrics_json["duplicate_match"]
    assert 0 < recorded["confidence"] < 0.70
