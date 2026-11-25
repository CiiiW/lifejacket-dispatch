"""The local console's four decisions, volunteer alerts, and reporter thread.

Uses the whole app (so route registration and the network boundary are the
real ones), a temporary database, and no network or model calls. Every
volunteer here comes from the fictional seed file.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.config import settings
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.models.db import get_session
from lifejacket.models.tables import (
    AssignmentRow,
    Base,
    IncidentEventRow,
    IncidentRow,
    ResponderRow,
)
from lifejacket.services import reporter_thread
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

JETTY_BEACH = (36.80968, -121.78995)  # the reporter app's demo-mode location


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(settings, "photo_storage_dir", tmp_path / "photos")
    scripted = ScriptedLLMClient.scenario("dolphin")
    monkeypatch.setattr("lifejacket.agents.base.get_client", lambda: scripted)
    client = TestClient(app)  # no lifespan: never touches the real lifejacket.db
    assert client.post("/volunteers/seed-demo").status_code == 200
    yield client, sessions
    app.dependency_overrides.clear()


def make_incident(sessions, incident_id="case1", severity="monitor", where=JETTY_BEACH,
                  connected=True):
    with sessions() as session:
        session.add(
            IncidentRow(
                incident_id=incident_id,
                status="awaiting_dispatch",
                severity_level=severity,
                latitude=where[0] if where else None,
                longitude=where[1] if where else None,
                species_common_name="Harbor seal",
            )
        )
        session.flush()
        key = reporter_thread.issue_key(session, incident_id) if connected else None
        session.commit()
    return key


def events(sessions, incident_id, kind):
    with sessions() as session:
        return [
            e.details
            for e in session.scalars(
                select(IncidentEventRow).where(
                    IncidentEventRow.incident_id == incident_id, IncidentEventRow.kind == kind
                )
            )
        ]


# --- Volunteers ---------------------------------------------------------------


def test_seed_is_fictional_and_idempotent(api):
    client, _ = api
    first = client.get("/volunteers/summary").json()
    assert first == {"total": 25, "available": 22, "fictional": 25}
    assert client.post("/volunteers/seed-demo").json() == first


def test_nearby_is_local_sorted_and_never_returns_phone_numbers(api):
    client, sessions = api
    make_incident(sessions)
    body = client.get("/incidents/case1/volunteers").json()
    assert body["task"] == "observe"
    vols = body["volunteers"]
    distances = [v["distance_km"] for v in vols]
    assert distances == sorted(distances) and max(distances) <= body["search_radius_km"]
    names = {v["name"] for v in vols}
    # Monterey Bay only: no San Francisco, Los Angeles or San Diego volunteers.
    assert "Ana Ruiz" in names and not names & {"Jordan Lee", "Sofia Alvarez", "Aiko Sato"}
    for v in vols:
        assert "phone" not in v and len(v["phone_last4"]) == 4
    by_name = {v["name"]: v for v in vols}
    assert by_name["Hannah Weiss"]["ineligible_reason"] == "Has paused alerts"
    assert by_name["Olivia Chen"]["in_range"] is False  # 15 km radius, ~27 km away
    assert by_name["Ana Ruiz"]["eligible"] is True


def test_critical_cases_only_take_trained_volunteers(api):
    client, sessions = api
    make_incident(sessions, severity="critical")
    body = client.get("/incidents/case1/volunteers").json()
    assert body["task"] == "support"
    by_name = {v["name"]: v for v in body["volunteers"]}
    assert by_name["Ana Ruiz"]["eligible"] is False
    assert "trained responder" in by_name["Ana Ruiz"]["ineligible_reason"]
    assert by_name["Marcus Bell"]["eligible"] is True


def test_alerts_are_simulated_all_or_nothing_and_kept_out_of_events(api):
    client, sessions = api
    make_incident(sessions)
    message = "LifeJacket: harbor seal at Jetty Beach. Can you check in?"

    # One ineligible volunteer (paused) means nobody is alerted.
    bad = client.post("/incidents/case1/volunteer-alerts",
                      json={"volunteer_ids": ["VOL_001", "VOL_007"], "message": message})
    assert bad.status_code == 422 and "Hannah Weiss" in bad.json()["detail"]
    assert client.get("/incidents/case1/volunteer-alerts").json() == []

    sent = client.post("/incidents/case1/volunteer-alerts",
                       json={"volunteer_ids": ["VOL_001", "VOL_003"], "message": message})
    assert sent.status_code == 200
    alerts = sent.json()
    assert [a["volunteer_name"] for a in alerts] == ["Ana Ruiz", "Priya Natarajan"]
    assert {a["delivery"] for a in alerts} == {"simulated"}
    assert {a["status"] for a in alerts} == {"awaiting_reply"}

    again = client.post("/incidents/case1/volunteer-alerts",
                        json={"volunteer_ids": ["VOL_001"], "message": message})
    assert again.status_code == 409
    unknown = client.post("/incidents/case1/volunteer-alerts",
                          json={"volunteer_ids": ["VOL_999"], "message": message})
    assert unknown.status_code == 404

    [details] = events(sessions, "case1", "volunteers_alerted")
    assert details["delivery"] == "simulated" and message not in str(details)
    nearby = client.get("/incidents/case1/volunteers").json()["volunteers"]
    assert {v["name"]: v["alert"]["status"] for v in nearby if v["alert"]} == {
        "Ana Ruiz": "awaiting_reply", "Priya Natarajan": "awaiting_reply"
    }


def test_replies_are_explicit_and_idempotent(api):
    client, sessions = api
    make_incident(sessions)
    [alert] = client.post("/incidents/case1/volunteer-alerts",
                          json={"volunteer_ids": ["VOL_001"], "message": "Check in?"}).json()
    url = f"/volunteers/alerts/{alert['alert_id']}/reply"
    assert client.post(url, json={"status": "checked_in"}).json()["status"] == "checked_in"
    assert client.post(url, json={"status": "checked_in"}).status_code == 200
    assert client.post(url, json={"status": "declined"}).status_code == 409
    assert events(sessions, "case1", "volunteer_reply") == [
        {"alert_id": alert["alert_id"], "volunteer_id": "VOL_001", "status": "checked_in"}
    ]


# --- Ignore -------------------------------------------------------------------


def test_ignore_closes_the_case_and_stands_down_volunteers(api):
    client, sessions = api
    make_incident(sessions)
    client.post("/incidents/case1/volunteer-alerts",
                json={"volunteer_ids": ["VOL_001"], "message": "Check in?"})
    result = client.post("/incidents/case1/ignore", json={"reason": "false_report"})
    assert result.json() == {"incident_id": "case1", "status": "cancelled",
                             "reason": "false_report", "volunteer_alerts_cancelled": 1}
    assert client.get("/incidents/case1/volunteer-alerts").json()[0]["status"] == "cancelled"
    assert client.post("/incidents/case1/ignore", json={"reason": "other"}).status_code == 409
    # A closed case takes no more alerts.
    closed = client.post("/incidents/case1/volunteer-alerts",
                         json={"volunteer_ids": ["VOL_003"], "message": "Check in?"})
    assert closed.status_code == 409


def test_healthy_animal_is_guidance_only(api):
    client, sessions = api
    make_incident(sessions)
    result = client.post("/incidents/case1/ignore", json={"reason": "healthy_animal"})
    assert result.json()["status"] == "guidance_only"


def test_ignore_refuses_once_a_team_has_accepted(api):
    client, sessions = api
    make_incident(sessions)
    with sessions() as session:
        session.add(ResponderRow(responder_id="org", name="Fictional team", kind="organisation"))
        session.add(AssignmentRow(incident_id="case1", responder_id="org", status="accepted"))
        session.commit()
    assert client.post("/incidents/case1/ignore", json={"reason": "other"}).status_code == 409


# --- Drone --------------------------------------------------------------------


def test_drone_survey_plans_a_simulation_launching_inland(api):
    client, sessions = api
    make_incident(sessions)
    plan = client.post("/incidents/case1/drone-survey", json={}).json()
    assert plan["status"] == "ready_for_review" and plan["synthetic"] is True
    assert plan["survey_south"] < JETTY_BEACH[0] < plan["survey_north"]
    assert plan["survey_west"] < JETTY_BEACH[1] < plan["survey_east"]
    assert plan["home_longitude"] > JETTY_BEACH[1]  # east of the animal
    assert plan["distance_m"] > 0 and plan["estimated_battery_remaining_percent"] > 25
    [details] = events(sessions, "case1", "drone_survey_planned")
    assert details["simulation_only"] is True and details["plan_id"] == plan["plan_id"]


@pytest.mark.parametrize(("where", "detail"), [((47.6, -122.3), "California"), (None, "location")])
def test_drone_survey_refuses_outside_the_simulation(api, where, detail):
    client, sessions = api
    make_incident(sessions, where=where)
    result = client.post("/incidents/case1/drone-survey", json={})
    assert result.status_code == 409 and detail in result.json()["detail"]


def test_decision_log_reads_in_order(api):
    client, sessions = api
    make_incident(sessions)
    [alert] = client.post("/incidents/case1/volunteer-alerts",
                          json={"volunteer_ids": ["VOL_001"], "message": "Check in?"}).json()
    client.post(f"/volunteers/alerts/{alert['alert_id']}/reply", json={"status": "checked_in"})
    client.post("/incidents/case1/drone-survey", json={})
    client.post("/incidents/case1/ignore", json={"reason": "animal_left", "note": "Swam off"})
    summaries = [d["summary"] for d in client.get("/incidents/case1/decisions").json()]
    assert summaries[0] == "Alerted 1 volunteer(s) to watch from a distance (simulated texts)"
    assert summaries[1] == "Ana Ruiz checked in"
    assert summaries[2].startswith("Drone survey planned: ")
    assert summaries[3] == 'Ignored: animal has left. Note: "Swam off"'


# --- Coordinator <-> reporter thread ------------------------------------------


def test_reporter_key_is_issued_once_at_intake_start(api):
    client, _ = api
    turn = client.post("/intake/start", json={}).json()
    key, incident_id = turn["reporter_key"], turn["incident_id"]
    assert key and len(key) >= 32
    assert client.get(f"/intake/{incident_id}").json()["reporter_key"] is None
    headers = {"X-Reporter-Key": key}
    assert client.get(f"/intake/{incident_id}/messages", headers=headers).json() == []


def test_thread_round_trip_and_reporter_projection(api):
    client, sessions = api
    key = make_incident(sessions)
    headers = {"X-Reporter-Key": key}

    sent = client.post("/incidents/case1/messages",
                       json={"body": "Is the seal still on the sand?", "author_ref": "coord_amy"})
    assert sent.status_code == 200
    reply = client.post("/intake/case1/messages", headers=headers,
                        json={"body": "  Yes, about 20 m from the water.  "})
    assert reply.json()["body"] == "Yes, about 20 m from the water."

    mine = client.get("/intake/case1/messages", headers=headers).json()
    assert [(m["sender"], m["body"]) for m in mine] == [
        ("team", "Is the seal still on the sand?"), ("you", "Yes, about 20 m from the water.")
    ]
    assert all(set(m) == {"message_id", "sender", "body", "sent_at"} for m in mine)

    theirs = client.get("/incidents/case1/messages").json()
    assert theirs["reporter_connected"] is True
    assert [m["author_ref"] for m in theirs["messages"]] == ["coord_amy", None]
    # Text stays out of the event record, which reaches agent prompts.
    for kind in ("reporter_message_sent", "reporter_message_received"):
        assert all(set(d) == {"message_id"} for d in events(sessions, "case1", kind))


@pytest.mark.parametrize("headers", [{}, {"X-Reporter-Key": "wrong"}])
def test_reporter_thread_needs_the_key(api, headers):
    client, sessions = api
    make_incident(sessions)
    client.post("/incidents/case1/messages", json={"body": "Can you see it?"})
    for response in (
        client.get("/intake/case1/messages", headers=headers),
        client.post("/intake/case1/messages", headers=headers, json={"body": "hi"}),
        client.get("/intake/nosuchcase/messages", headers=headers),
    ):
        assert response.status_code == 403
        assert response.json()["detail"] == "Not authorised for this report's messages"


def test_cannot_message_a_report_with_no_reporter_app(api):
    client, sessions = api
    make_incident(sessions, connected=False)
    assert client.get("/incidents/case1/messages").json()["reporter_connected"] is False
    assert client.post("/incidents/case1/messages", json={"body": "hi"}).status_code == 409


def test_every_new_route_is_blocked_in_network_mode(monkeypatch):
    monkeypatch.setattr(settings, "network_auth_enabled", True)
    client = TestClient(app)
    for method, path in [
        ("GET", "/incidents/x/volunteers"), ("POST", "/incidents/x/volunteer-alerts"),
        ("POST", "/incidents/x/ignore"), ("POST", "/incidents/x/drone-survey"),
        ("GET", "/incidents/x/decisions"), ("GET", "/incidents/x/messages"),
        ("POST", "/incidents/x/messages"), ("GET", "/intake/x/messages"),
        ("POST", "/intake/x/messages"), ("GET", "/volunteers/summary"),
        ("POST", "/volunteers/seed-demo"), ("POST", "/volunteers/alerts/1/reply"),
    ]:
        assert client.request(method, path).status_code == 403, (method, path)
