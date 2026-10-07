from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.api.routes.incidents import (
    LogRequest,
    StatusUpdate,
    log_incident,
    update_status,
)
from lifejacket.api.routes.responders import (
    AssignRequest,
    RespondRequest,
    assign_responder,
    respond_to_assignment,
)
from lifejacket.models import repository
from lifejacket.models.db import get_session
from lifejacket.models.schemas import Incident, IncidentStatus
from lifejacket.models.tables import IncidentEventRow, IncidentRow
from lifejacket.services.coordination import get_incident_history
from lifejacket.services.events import record_event
from lifejacket.services.handover import build_handover
from sqlalchemy import select
from test_coordination import db as coordination_db

db = coordination_db
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


def events(db):
    return list(db.scalars(select(IncidentEventRow).order_by(IncidentEventRow.id)))


def test_offer_response_and_field_changes_keep_actor_and_previous_values(db):
    offer = assign_responder(
        AssignRequest(
            incident_id="original", responder_id="ready", approved_by="coordinator-test"
        ),
        db,
    )
    respond_to_assignment(
        offer["assignment_id"], RespondRequest(accept=False, note="Team occupied"), db
    )
    update_status("original", StatusUpdate(status="en_route", responder_id="ready"), db)
    records = events(db)
    assert [r.kind for r in records] == [
        "assignment_offered",
        "incident_changed",
        "assignment_response",
        "incident_changed",
        "incident_changed",
    ]
    assert records[0].actor_ref == "coordinator-test"
    assert records[2].details["note"] == "Team occupied"
    assert records[2].details["before"] == "offered"
    assert records[2].details["after"] == "declined"
    assert records[-1].details["changes"]["status"] == {
        "before": "awaiting_dispatch",
        "after": "en_route",
    }


def test_noop_status_does_not_invent_transition(db):
    update_status("original", StatusUpdate(status="awaiting_dispatch"), db)
    assert events(db) == []


def test_outcome_records_source_and_closure(db):
    log_incident("original", LogRequest(responder_id="ready", outcome="not_found"), db)
    records = events(db)
    assert records[0].kind == "outcome_logged"
    assert records[0].details["log_id"]
    assert records[0].details["outcome"] == "not_found"
    assert records[1].details["changes"]["status"]["after"] == "resolved"


def test_event_rollback_is_atomic(db):
    incident = repository.load_incident(db, "original")
    incident.status = IncidentStatus.ON_SCENE
    repository.save_incident(db, incident)
    assert events(db)
    db.rollback()
    assert events(db) == []
    assert db.get(IncidentRow, "original").status == "awaiting_dispatch"


def test_creation_and_health_change_through_repository(db):
    repository.save_incident(db, Incident(incident_id="new", status=IncidentStatus.INTAKE))
    db.commit()
    assert events(db)[0].kind == "incident_created"
    incident = repository.load_incident(db, "original")
    incident.metrics["health"] = {"awaiting_retry": True}
    repository.save_incident(db, incident)
    db.commit()
    assert events(db)[-1].details["changes"]["requires_human_review"] == {
        "before": False,
        "after": True,
    }
    report = build_handover(db, NOW, NOW + timedelta(hours=8))
    original = next(row for row in report.current_carryover if row.incident_id == "original")
    assert "human_review" in [task.kind for task in original.tasks]


def test_legacy_carryover_has_no_fabricated_events(db):
    report = build_handover(db, NOW, NOW + timedelta(hours=8))
    assert report.changes == []
    assert [row.incident_id for row in report.current_carryover] == ["original"]
    assert report.current_carryover[0].tasks[0].kind == "needs_assignment"
    assert "current snapshot" in report.limitations[1]


def test_time_window_is_half_open_and_normalizes_offsets(db):
    for time in [NOW - timedelta(seconds=1), NOW, NOW + timedelta(hours=8)]:
        db.add(
            IncidentEventRow(
                incident_id="original",
                recorded_at=time.replace(tzinfo=None),
                kind="incident_changed",
                details={},
            )
        )
    db.commit()
    report = build_handover(db, NOW, NOW + timedelta(hours=8))
    assert len(report.changes) == 1
    assert report.changes[0].recorded_at == NOW
    assert report.changes[0].source_ref.startswith("incident_events:")
    shifted = NOW.astimezone(timezone(timedelta(hours=-5)))
    same = build_handover(db, shifted, shifted + timedelta(hours=8))
    assert same.start == NOW
    assert same.changes == report.changes


@pytest.mark.parametrize(
    "start,end",
    [
        (NOW.replace(tzinfo=None), NOW),
        (NOW, NOW),
        (NOW, NOW - timedelta(hours=1)),
        (NOW, NOW + timedelta(days=8)),
    ],
)
def test_invalid_windows_rejected(db, start, end):
    with pytest.raises(ValueError):
        build_handover(db, start, end)


def test_limits_are_visible(db, monkeypatch):
    monkeypatch.setattr("lifejacket.services.handover.EVENT_LIMIT", 1)
    monkeypatch.setattr("lifejacket.services.handover.CASE_LIMIT", 1)
    db.add(IncidentRow(incident_id="second", status="intake"))
    for _ in range(2):
        db.add(
            IncidentEventRow(
                incident_id="original",
                recorded_at=NOW.replace(tzinfo=None),
                kind="incident_changed",
                details={},
            )
        )
    db.commit()
    report = build_handover(db, NOW, NOW + timedelta(hours=8))
    assert report.changes_truncated and report.carryover_truncated
    assert len(report.changes) == len(report.current_carryover) == 1


def test_history_keeps_recorded_changes_separate_from_snapshots(db):
    record_event(db, "original", "incident_changed", {"changes": {}})
    db.commit()
    history = get_incident_history(db, "duplicate")
    recorded = [entry for entry in history.entries if entry.kind == "recorded_event"]
    assert len(recorded) == 1
    assert recorded[0].data["timestamp_basis"] == "UTC"
    assert recorded[0].incident_id == "original"


def test_http_requires_explicit_timezone_window(db):
    app.dependency_overrides[get_session] = lambda: db
    try:
        client = TestClient(app)
        assert client.get("/coordination/handover").status_code == 422
        assert (
            client.get(
                "/coordination/handover",
                params={
                    "start": NOW.isoformat(),
                    "end": (NOW + timedelta(hours=8)).isoformat(),
                },
            ).json()["scope"]
            == "installation-wide"
        )
        assert (
            client.get(
                "/coordination/handover",
                params={"start": NOW.replace(tzinfo=None).isoformat(), "end": NOW.isoformat()},
            ).status_code
            == 422
        )
    finally:
        app.dependency_overrides.clear()
