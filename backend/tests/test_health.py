"""Model failures: retries, error types, fail-safes, and the per-incident health record.

Everything here simulates a broken model -- unreachable, or replying with
rubbish -- and checks three things: the request does not crash, the fail-safe
for that step is the conservative one, and the incident's health record says
what happened. No network and no API key, like the rest of the suite.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.chatbot.playground import ChatPlayground
from lifejacket.chatbot.session import StepAction
from lifejacket.config import settings
from lifejacket.llm.client import LLMCallError, LLMClient, LLMError, LLMResponseError
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.models.db import get_session
from lifejacket.models.schemas import EnvironmentalContext, IncidentStatus
from lifejacket.models.tables import Base
from lifejacket.services import health
from lifejacket.services.pipeline import SERVICE_RETRY_MESSAGE
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No geocoding, and no real waiting between retries."""
    monkeypatch.setattr("lifejacket.services.pipeline.reverse_geocode", lambda *a: None)
    monkeypatch.setattr("lifejacket.llm.client.time.sleep", lambda seconds: None)


# ---------------------------------------------------------------------------
# LLMClient: which error, after how many attempts
# ---------------------------------------------------------------------------


def _client_with_replies(monkeypatch, replies: list) -> LLMClient:
    """A real `LLMClient` whose SDK is replaced by a list of canned outcomes.

    Each item is either an exception to raise or the text of a reply.
    """
    outcomes = iter(replies)

    def generate_content(**kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome, usage_metadata=None)

    client = LLMClient(model="test", project="test", location="test", max_retries=3)
    client._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    # Building real SDK content objects is not what is under test here.
    monkeypatch.setattr(LLMClient, "_build_contents", staticmethod(lambda prompt, images: []))
    return client


def test_unreachable_model_raises_call_error_with_attempt_count(monkeypatch):
    client = _client_with_replies(monkeypatch, [ConnectionError("down")] * 3)

    with pytest.raises(LLMCallError) as caught:
        client.generate_json("prompt", SCHEMA)

    assert caught.value.kind == "call_failed"
    assert caught.value.attempts == 3
    assert isinstance(caught.value, LLMError)  # existing `except LLMError` still works


def test_unusable_reply_raises_response_error(monkeypatch):
    client = _client_with_replies(monkeypatch, ["not json", "", "[1, 2]"])

    with pytest.raises(LLMResponseError) as caught:
        client.generate_json("prompt", SCHEMA)

    assert caught.value.kind == "bad_response"
    assert caught.value.attempts == 3


def test_error_kind_reflects_the_last_failure(monkeypatch):
    client = _client_with_replies(
        monkeypatch, ["not json", "not json", ConnectionError("down")]
    )

    with pytest.raises(LLMCallError):
        client.generate_json("prompt", SCHEMA)


def test_recovered_retry_is_not_an_error_but_is_counted(monkeypatch):
    client = _client_with_replies(monkeypatch, [ConnectionError("blip"), '{"ok": true}'])

    response = client.generate_json("prompt", SCHEMA)

    assert response.data == {"ok": True}
    assert response.attempts == 2


# ---------------------------------------------------------------------------
# The health record itself
# ---------------------------------------------------------------------------


def test_health_record_counts_calls_retries_failures_and_fallbacks():
    metrics: dict = {}
    assert not health.had_problems(metrics) and not health.needs_review(metrics)

    health.record_success(metrics, attempts=1)
    health.record_success(metrics, attempts=3)  # two retries, then fine
    assert health.had_problems(metrics)
    assert not health.needs_review(metrics)  # recovered: no human needed

    health.record_failure(metrics, "report", "call_failed", attempts=3, detail="x" * 999)
    health.record_fallback(metrics, health.FALLBACK_REPORT_UNAVAILABLE)
    health.record_fallback(metrics, health.FALLBACK_REPORT_UNAVAILABLE)  # not doubled

    record = metrics["health"]
    assert record["llm_calls"] == 3
    assert record["llm_retries"] == 4
    assert record["failed_calls"] == 1
    assert record["fallbacks"] == ["report_unavailable"]
    assert record["failures"][0]["agent"] == "report"
    assert len(record["failures"][0]["detail"]) == 300  # truncated for the console
    assert health.needs_review(metrics)


def test_health_updates_replace_the_record_rather_than_editing_it():
    """Guards the copy-on-write in `health._updated`; the reason is explained there."""
    metrics: dict = {}
    health.record_success(metrics)
    before = metrics["health"]

    health.record_failure(metrics, "report", "call_failed", attempts=3, detail="boom")

    assert metrics["health"] is not before
    assert before["failed_calls"] == 0  # the old record was left untouched


# ---------------------------------------------------------------------------
# Pipeline fail-safes, in memory
# ---------------------------------------------------------------------------


def _scenario_failing(agent: str, error: Exception, at: int = 0) -> ScriptedLLMClient:
    """The sea lion scenario, with one call to `agent` replaced by a failure."""
    client = ScriptedLLMClient.scenario("sea_lion")
    client.script[agent].insert(at, error)
    return client


def _start(client: ScriptedLLMClient) -> ChatPlayground:
    return ChatPlayground.full(client=client, live_context=False, verbose=False)


def test_identification_failure_asks_the_reporter_to_retry_then_recovers():
    client = _scenario_failing("identification", LLMCallError("Vertex down", attempts=3))
    chat = _start(client)

    # The failed step did not crash, and nothing was decided.
    turn = chat.last_turn
    assert turn.action is StepAction.SERVICE_RETRY
    assert turn.message == SERVICE_RETRY_MESSAGE
    assert turn.awaiting_reply and not turn.complete
    assert chat.state.identification is None

    record = chat.incident.metrics["health"]
    assert record["failed_calls"] == 1
    assert record["llm_retries"] == 2
    assert record["awaiting_retry"] is True
    assert record["failures"][0]["agent"] == "identification"
    assert record["failures"][0]["kind"] == "call_failed"
    assert health.needs_review(chat.incident.metrics)

    # "Try again": advancing re-runs the same step, with no new reporter message.
    turn = chat._advance()
    assert turn.action is StepAction.ASK_CLARIFYING_QUESTION
    assert chat.state.identification is not None
    assert chat.incident.metrics["health"]["awaiting_retry"] is False

    chat.answer("yes, green netting")
    assert chat.done
    assert chat.incident.status is IncidentStatus.AWAITING_DISPATCH
    assert chat.incident.report is not None
    # Recovered, so no review is needed on health grounds -- but the failure
    # stays on the record.
    assert not health.needs_review(chat.incident.metrics)
    assert chat.incident.metrics["health"]["failed_calls"] == 1


def test_assessment_failure_keeps_the_reporters_answer():
    # The second assessment call (after the reporter answers) is the one that fails.
    client = _scenario_failing("assessment", LLMResponseError("not JSON", attempts=3), at=1)
    chat = _start(client)

    turn = chat.answer("yes, green netting")
    assert turn.action is StepAction.SERVICE_RETRY
    assert chat.incident.metrics["health"]["failures"][0]["kind"] == "bad_response"

    turn = chat._advance()  # retry
    assert chat.done
    assert chat.state.assessment.injury.entanglement  # the answer was not lost
    reporter_messages = [
        m.content for m in chat.state.transcript if m.role.value == "reporter"
    ]
    assert reporter_messages == ["yes, green netting"]  # and was not duplicated


def test_report_failure_still_sends_the_incident_to_coordinators(caplog):
    client = _scenario_failing("report", LLMCallError("Vertex down", attempts=3))
    chat = _start(client)

    with caplog.at_level(logging.WARNING, logger="lifejacket.services.health"):
        chat.answer("yes, green netting")

    incident = chat.incident
    assert chat.done
    assert incident.report is None
    assert incident.status is IncidentStatus.AWAITING_DISPATCH  # not lost
    assert incident.dispatch_candidates is not None
    assert incident.assessment.requires_human_review
    assert incident.metrics["health"]["fallbacks"] == ["report_unavailable"]
    assert "guardrail" not in incident.metrics  # nothing to check
    assert "guardrail" not in [c.agent for c in client.calls]
    # The closing message makes no promise that depends on the report.
    assert "rescue coordinators" in chat.last_turn.message
    # And the summary line stands out in the log.
    assert any("health:" in r.message and r.levelno == logging.WARNING for r in caplog.records)


def test_guardrail_failure_holds_the_report_and_says_the_check_did_not_run():
    client = _scenario_failing("guardrail", LLMCallError("Vertex down", attempts=3))
    chat = _start(client)
    chat.answer("yes, green netting")

    incident = chat.incident
    assert incident.report is not None  # the report exists...
    assert incident.assessment.requires_human_review  # ...but is held
    verdict = incident.metrics["guardrail"]
    assert verdict["check_failed"] is True
    assert verdict["is_grounded"] is False and verdict["is_safe"] is False
    assert incident.metrics["health"]["fallbacks"] == ["guardrail_check_failed"]
    assert incident.metrics["health"]["failures"][0]["agent"] == "guardrail"


def test_clean_run_records_calls_and_no_problems():
    chat = _start(ScriptedLLMClient.scenario("sea_lion"))
    chat.answer("yes, green netting")

    record = chat.incident.metrics["health"]
    assert record == {
        "llm_calls": 5,  # identification, assessment x2, report, guardrail
        "llm_retries": 0,
        "failed_calls": 0,
        "failures": [],
        "fallbacks": [],
        "awaiting_retry": False,
    }
    assert not health.had_problems(chat.incident.metrics)
    assert chat.incident.metrics["guardrail"]["check_failed"] is False


# ---------------------------------------------------------------------------
# Over HTTP: nothing crashes, health survives save and reload
# ---------------------------------------------------------------------------


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

    scripted = ScriptedLLMClient.scenario("sea_lion")
    monkeypatch.setattr("lifejacket.agents.base.get_client", lambda: scripted)
    monkeypatch.setattr(
        "lifejacket.services.pipeline.gather_context",
        lambda location: EnvironmentalContext(location=location, unavailable=["tide"]),
    )

    yield TestClient(app), scripted
    app.dependency_overrides.clear()


def _report_until_location(client: TestClient) -> tuple[str, dict]:
    incident_id = client.post("/intake/start", json={}).json()["incident_id"]
    client.post(
        f"/intake/{incident_id}/photo",
        files={"file": ("animal.jpg", b"\xff\xd8\xff fake jpeg", "image/jpeg")},
    )
    response = client.post(
        f"/intake/{incident_id}/location", json={"latitude": 36.8, "longitude": -121.79}
    )
    assert response.status_code == 200  # a model failure is not a server error
    return incident_id, response.json()


def test_failed_step_over_http_is_a_retry_turn_and_is_visible_to_coordinators(api):
    client, scripted = api
    scripted.script["identification"].insert(0, LLMCallError("Vertex down", attempts=3))

    incident_id, turn = _report_until_location(client)
    assert turn["service_error"] is True
    assert turn["action"] == "service_retry"
    assert turn["awaiting_reply"] is True

    # Reopening the app shows the same turn, not an empty screen.
    resumed = client.get(f"/intake/{incident_id}").json()
    assert resumed["service_error"] is True
    assert resumed["message"] == turn["message"]

    # The stalled intake is on the console, flagged, with the reason.
    detail = client.get(f"/incidents/{incident_id}").json()
    assert detail["requires_human_review"] is True
    assert detail["health"]["awaiting_retry"] is True
    assert detail["health"]["failures"][0]["agent"] == "identification"

    # "Try again" re-runs the step without adding to the conversation.
    turn = client.post(f"/intake/{incident_id}/retry").json()
    assert turn["service_error"] is False
    assert turn["action"] == "ask_clarifying_question"
    assert turn["identified_as"] == "California sea lion"

    turn = client.post(f"/intake/{incident_id}/reply", json={"text": "yes, netting"}).json()
    assert turn["complete"]

    detail = client.get(f"/incidents/{incident_id}").json()
    assert detail["report"]["headline"]
    # Saved and reloaded across five requests, and still all there.
    assert detail["health"]["llm_calls"] == 6
    assert detail["health"]["failed_calls"] == 1
    assert detail["health"]["awaiting_retry"] is False
    assert [m["role"] for m in detail["transcript"]].count("reporter") == 1


def test_repeated_failures_are_each_saved(api):
    """A second failure in a row is saved too, checked through the database.

    Nothing in `metrics` changes on the second failure except the nested
    health record, so this is the save most at risk of being missed.
    """
    client, scripted = api
    for _ in range(2):
        scripted.script["identification"].insert(0, LLMCallError("Vertex down", attempts=3))

    incident_id, turn = _report_until_location(client)
    assert turn["service_error"] is True
    turn = client.post(f"/intake/{incident_id}/retry").json()
    assert turn["service_error"] is True

    detail = client.get(f"/incidents/{incident_id}").json()
    assert detail["health"]["failed_calls"] == 2
    assert len(detail["health"]["failures"]) == 2


def test_retry_with_nothing_to_retry_does_not_spend_a_question(api):
    client, scripted = api
    incident_id, turn = _report_until_location(client)
    assert turn["action"] == "ask_clarifying_question"
    calls_before = len(scripted.calls)

    again = client.post(f"/intake/{incident_id}/retry").json()

    assert again["message"] == turn["message"]
    assert again["questions_asked"] == turn["questions_asked"]
    assert len(scripted.calls) == calls_before  # no model call was made


def test_report_failure_over_http_reaches_the_console_without_a_report(api):
    client, scripted = api
    scripted.script["report"].insert(0, LLMCallError("Vertex down", attempts=3))

    incident_id, _ = _report_until_location(client)
    response = client.post(f"/intake/{incident_id}/reply", json={"text": "yes, netting"})
    assert response.status_code == 200
    assert response.json()["complete"]

    detail = client.get(f"/incidents/{incident_id}").json()
    assert detail["status"] == "awaiting_dispatch"
    assert detail["report"] is None
    assert detail["requires_human_review"] is True
    assert detail["severity_level"] == "critical"  # triage did not depend on the report
    assert detail["health"]["fallbacks"] == ["report_unavailable"]
