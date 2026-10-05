"""A whole intake conversation over HTTP, against a throwaway database.

The pipeline tests run in memory. This one goes through the real routes, so
conversation state is saved to SQLite and reloaded between every request --
which is exactly what the phone app does, and where a field missing from
serialisation would silently break the conversation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.config import settings
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.models.db import get_session
from lifejacket.models.schemas import EnvironmentalContext
from lifejacket.models.tables import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(settings, "photo_storage_dir", tmp_path / "photos")

    # A fresh agent is built per request, so every request must get the SAME
    # scripted client -- otherwise each one would restart the script.
    scripted = ScriptedLLMClient.scenario("dolphin")
    monkeypatch.setattr("lifejacket.agents.base.get_client", lambda: scripted)

    # Keep the test off the network.
    monkeypatch.setattr(
        "lifejacket.services.pipeline.gather_context",
        lambda location: EnvironmentalContext(location=location, unavailable=["tide"]),
    )
    monkeypatch.setattr("lifejacket.services.pipeline.reverse_geocode", lambda *a: None)

    # Not used as a context manager, so the app's startup hook (which would
    # create the real lifejacket.db) does not run.
    yield TestClient(app), scripted
    app.dependency_overrides.clear()


def test_full_conversation_over_http(api):
    client, scripted = api

    turn = client.post("/intake/start", json={}).json()
    incident_id = turn["incident_id"]
    assert turn["action"] == "request_photo"

    turn = client.post(
        f"/intake/{incident_id}/photo",
        files={"file": ("dolphin.jpg", b"\xff\xd8\xff fake jpeg", "image/jpeg")},
    ).json()
    assert turn["action"] == "request_location"

    # Location triggers the first identification pass -- no scripted questions.
    turn = client.post(
        f"/intake/{incident_id}/location", json={"latitude": 36.8, "longitude": -121.79}
    ).json()
    assert turn["action"] == "ask_clarifying_question"
    assert "beak" in turn["message"]

    # This answer must reach the identification agent on the NEXT request,
    # after the state has been saved and reloaded.
    turn = client.post(f"/intake/{incident_id}/reply", json={"text": "long beak"}).json()
    assert turn["identified_as"] == "Oceanic dolphins"
    assert turn["taxon_rank"] == "family"
    assert "breathing" in turn["message"]  # now the assessment agent is asking

    turn = client.post(f"/intake/{incident_id}/reply", json={"text": "yes"}).json()
    assert turn["complete"]
    assert turn["severity_level"] == "critical"

    detail = client.get(f"/incidents/{incident_id}").json()
    assert detail["taxon_rank"] == "family"
    assert [s["common_name"] for s in detail["species_candidates"]] == [
        "Common dolphin",
        "Bottlenose dolphin",
    ]
    assert detail["report"]["headline"]
    assert [c.agent for c in scripted.calls] == [
        "identification", "identification", "assessment", "assessment", "report", "guardrail",
    ]


def test_photo_is_reachable_from_the_incident(api):
    """A responder must be able to see what the reporter actually sent.

    The agents read the photo bytes straight off the upload request, so until
    this existed nothing ever read them back and the console had no way to
    show the animal.
    """
    client, _ = api

    incident_id = client.post("/intake/start", json={}).json()["incident_id"]
    client.post(
        f"/intake/{incident_id}/photo",
        files={"file": ("seal.jpg", b"\xff\xd8\xff fake jpeg bytes", "image/jpeg")},
    )

    detail = client.get(f"/incidents/{incident_id}").json()
    assert len(detail["photos"]) == 1
    photo = detail["photos"][0]
    assert photo["content_type"] == "image/jpeg"

    # The map feed carries the first photo too, so list rows can show a
    # thumbnail without a request each.
    pin = next(p for p in client.get("/incidents").json() if p["incident_id"] == incident_id)
    assert pin["photo_url"] == photo["url"]

    image = client.get(photo["url"])
    assert image.status_code == 200
    assert image.content == b"\xff\xd8\xff fake jpeg bytes"


def test_photo_404s_for_the_wrong_incident(api):
    """Photo ids are scoped to their incident, not globally guessable."""
    client, _ = api

    first = client.post("/intake/start", json={}).json()["incident_id"]
    client.post(
        f"/intake/{first}/photo",
        files={"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    photo_id = client.get(f"/incidents/{first}").json()["photos"][0]["photo_id"]

    second = client.post("/intake/start", json={}).json()["incident_id"]
    assert client.get(f"/incidents/{second}/photos/{photo_id}").status_code == 404


def test_route_falls_back_to_a_straight_line_without_a_key(api, monkeypatch):
    """No OpenRouteService key must not mean no map line.

    It means a straight line, flagged as one, so the console can dash it and
    nobody reads it as a drivable distance.
    """
    from lifejacket.config import settings as live_settings

    monkeypatch.setattr(live_settings, "ors_api_key", "")
    client, _ = api

    incident_id = client.post("/intake/start", json={}).json()["incident_id"]
    client.post(
        f"/intake/{incident_id}/photo",
        files={"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    client.post(f"/intake/{incident_id}/location", json={"latitude": 36.8, "longitude": -121.79})

    client.post("/responders/seed")
    responder_id = client.get("/responders").json()[0]["responder_id"]
    client.post(
        f"/responders/{responder_id}/location", json={"latitude": 37.0, "longitude": -122.0}
    )

    route = client.get(f"/incidents/{incident_id}/route", params={"responder_id": responder_id})
    assert route.status_code == 200
    body = route.json()
    assert body["source"] == "straight_line"
    assert len(body["coordinates"]) == 2
    assert body["distance_km"] > 0
    # GeoJSON order: longitude first. Getting this backwards puts the route in
    # the Indian Ocean, so it is worth asserting.
    assert body["coordinates"][0][0] == -122.0


def test_closed_incidents_are_hidden_unless_asked_for(api):
    """A logged incident leaves the open list but is reachable for history.

    The responder console relies on this: logging an outcome resolves the
    incident, and without `include_closed` the demo would appear to lose it.
    """
    client, _ = api

    incident_id = client.post("/intake/start", json={}).json()["incident_id"]
    client.post(
        f"/intake/{incident_id}/photo",
        files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    client.post(f"/intake/{incident_id}/location", json={"latitude": 36.8, "longitude": -121.79})

    def listed(**params):
        return [row["incident_id"] for row in client.get("/incidents", params=params).json()]

    assert incident_id in listed()

    logged = client.post(
        f"/incidents/{incident_id}/log",
        json={
            "responder_id": "org_test",
            "confirmed_species": "Harbor seal",
            "outcome": "rescued",
        },
    )
    assert logged.status_code == 200
    assert logged.json()["status"] == "resolved"

    assert incident_id not in listed()
    assert incident_id in listed(include_closed=True)


def test_any_text_is_a_valid_answer(api):
    """Options are shortcuts, not a whitelist."""
    client, _ = api
    incident_id = client.post("/intake/start", json={}).json()["incident_id"]
    client.post(
        f"/intake/{incident_id}/photo",
        files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    client.post(f"/intake/{incident_id}/location", json={"latitude": 36.8, "longitude": -121.79})

    response = client.post(
        f"/intake/{incident_id}/reply", json={"text": "hard to say, it's facing away"}
    )
    assert response.status_code == 200
