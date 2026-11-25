"""The reporter app's Communications and My reports tabs, and the console inbox.

Either side may start a thread now; the console lists threads with the ones
owed a reply first. A device lists its own reports by the keys it holds, and
the app's waiting line names the intake step that is running.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.models.db import get_session
from lifejacket.models.tables import Base, IncidentRow
from lifejacket.services import progress, reporter_thread
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def api(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    yield TestClient(app), sessions
    app.dependency_overrides.clear()


def make_incident(sessions, incident_id, *, connected=True, status="awaiting_dispatch", **fields):
    with sessions() as session:
        session.add(IncidentRow(incident_id=incident_id, status=status, latitude=36.81,
                                longitude=-121.79, place_name="Moss Landing", **fields))
        session.flush()
        key = reporter_thread.issue_key(session, incident_id) if connected else None
        session.commit()
    return key


def test_a_reporter_can_write_first_and_the_console_sees_a_reply_is_owed(api):
    client, sessions = api
    key = make_incident(sessions, "otter", species_common_name="Southern sea otter",
                        reporter_phone="+1 831 555 0142")
    make_incident(sessions, "seal")
    make_incident(sessions, "drone", connected=False)  # nobody to message: never listed

    sent = client.post("/intake/otter/messages", headers={"X-Reporter-Key": key},
                       json={"body": "It just moved into the water."})
    assert sent.status_code == 200 and sent.json()["sender"] == "you"

    threads = client.get("/communications/threads").json()
    assert [t["incident_id"] for t in threads] == ["otter", "seal"]
    otter = threads[0]
    assert otter["awaiting_reply"] is True
    assert otter["reporter_phone"] == "+1 831 555 0142"
    assert otter["last_message"]["sender"] == "reporter"
    assert threads[1]["message_count"] == 0 and threads[1]["awaiting_reply"] is False

    client.post("/incidents/otter/messages", json={"body": "Thanks, we'll look from the road."})
    assert client.get("/communications/threads").json()[0]["awaiting_reply"] is False


def test_my_reports_answers_only_for_keys_that_match(api):
    client, sessions = api
    mine = make_incident(sessions, "mine", species_common_name="Harbor seal",
                         severity_level="monitor", status="en_route")
    make_incident(sessions, "theirs")
    early = make_incident(sessions, "draft", status="intake")
    client.post("/incidents/mine/messages", json={"body": "Is it still there?"})

    body = {"reports": [
        {"incident_id": "mine", "reporter_key": mine},
        {"incident_id": "theirs", "reporter_key": mine},  # someone else's report
        {"incident_id": "missing", "reporter_key": mine},
        {"incident_id": "draft", "reporter_key": early},
    ]}
    reports = client.post("/intake/my-reports", json=body).json()
    assert [r["incident_id"] for r in reports] == ["mine", "draft"]
    first = reports[0]
    assert first["status"] == "en_route" and first["complete"] is True
    assert first["species_common_name"] == "Harbor seal" and first["severity_level"] == "monitor"
    assert first["team_message_count"] == 1 and first["last_message"]["sender"] == "team"
    assert first["created_at"].endswith(("Z", "+00:00"))
    assert reports[1]["complete"] is False
    # Nothing about who is handling the case.
    assert "reporter_phone" not in first and "assigned_responder_id" not in first

    too_many = {"reports": [{"incident_id": f"c{i}", "reporter_key": "k"} for i in range(51)]}
    assert client.post("/intake/my-reports", json=too_many).status_code == 422


def test_progress_names_the_running_step_and_needs_the_key(api):
    client, sessions = api
    key = make_incident(sessions, "otter", status="assessing")
    url, headers = "/intake/otter/progress", {"X-Reporter-Key": key}

    assert client.get(url, headers=headers).json() == {"step": None}
    progress.mark("otter", "validation")
    assert client.get(url, headers=headers).json() == {"step": "validation"}
    assert client.get(url).status_code == 403
    assert client.get(url, headers={"X-Reporter-Key": "wrong"}).status_code == 403
    progress.clear("otter")
    assert client.get(url, headers=headers).json() == {"step": None}


def test_stale_progress_expires(monkeypatch):
    progress.mark("slow", "report")
    clock = progress.time.monotonic() + progress.STALE_AFTER_SECONDS + 1
    monkeypatch.setattr(progress.time, "monotonic", lambda: clock)
    assert progress.current("slow") is None


def test_the_pipeline_marks_every_step_it_runs(monkeypatch):
    from lifejacket.chatbot.playground import ChatPlayground
    from lifejacket.llm.fake import ScriptedLLMClient

    monkeypatch.setattr("lifejacket.services.pipeline.reverse_geocode", lambda *a: None)
    steps: list[str] = []
    monkeypatch.setattr(progress, "mark", lambda _incident, step: steps.append(step))

    client = ScriptedLLMClient.scenario("sea_lion")
    chat = ChatPlayground.full(client=client, live_context=False, verbose=False)
    chat.answer("yes, green netting")
    assert chat.done

    agents = [step for step in steps if step not in {"context", "matching"}]
    assert agents == [c.agent for c in client.calls]
    assert steps[-1] == "matching"
    assert set(steps) <= set(progress.STEPS)
