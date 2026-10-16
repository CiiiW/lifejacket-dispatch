"""Coordination evidence and pending work against a real throwaway database."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.models.db import get_session
from lifejacket.models.tables import (
    AssignmentRow,
    Base,
    ChatMessageRow,
    IncidentLogRow,
    IncidentRow,
    ResponderRow,
)
from lifejacket.services.coordination import (
    get_assignments,
    get_available_responders,
    get_incident_history,
    get_pending_tasks,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

NOW = datetime(2026, 10, 7, 12)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'coordination.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                IncidentRow(
                    incident_id="original", status="awaiting_dispatch", created_at=NOW
                ),
                IncidentRow(
                    incident_id="duplicate",
                    status="cancelled",
                    duplicate_of="original",
                    created_at=NOW + timedelta(minutes=2),
                ),
                IncidentRow(incident_id="unrelated", status="resolved", created_at=NOW),
                ResponderRow(
                    responder_id="ready",
                    name="Ready team",
                    kind="volunteer",
                    is_active=True,
                    is_on_duty=True,
                ),
                ResponderRow(
                    responder_id="off",
                    name="Off duty",
                    kind="organisation",
                    is_active=True,
                    is_on_duty=False,
                ),
                ResponderRow(
                    responder_id="inactive",
                    name="Inactive",
                    kind="volunteer",
                    is_active=False,
                    is_on_duty=True,
                ),
            ]
        )
        session.commit()
        yield session
    engine.dispose()


def offer(db, status="offered", incident_id="original"):
    row = AssignmentRow(
        incident_id=incident_id,
        responder_id="ready",
        status=status,
        offered_at=NOW,
        responded_at=NOW if status != "offered" else None,
    )
    db.add(row)
    db.commit()
    db.expire_all()
    return row


def test_linked_reports_are_evidence_not_fabricated_status_events(db):
    db.add_all(
        [
            ChatMessageRow(
                incident_id="duplicate",
                role="reporter",
                content="Now three animals",
                created_at=NOW + timedelta(minutes=3),
            ),
            ChatMessageRow(
                incident_id="unrelated", role="reporter", content="Private unrelated case"
            ),
            IncidentLogRow(
                incident_id="original",
                responder_id="ready",
                outcome="not_found",
                created_at=NOW + timedelta(minutes=5),
            ),
        ]
    )
    db.commit()
    history = get_incident_history(db, "duplicate")
    assert history.incident_id == "original"
    assert history.duplicate_of == "original"
    assert {entry.incident_id for entry in history.entries} == {"original", "duplicate"}
    assert [entry.recorded_at for entry in history.entries] == sorted(
        entry.recorded_at for entry in history.entries
    )
    assert any(entry.kind == "closing_log" for entry in history.entries)
    assert all(entry.source_ref for entry in history.entries)
    assert not any(entry.kind == "status_change" for entry in history.entries)
    assert "current snapshot" in history.limitations[0]


def test_decline_needs_assignment_but_offer_is_not_acceptance(db):
    assignment = offer(db, "declined")
    assert [task.kind for task in get_pending_tasks(db, "original")] == ["needs_assignment"]
    assignment.status = "offered"
    db.commit()
    db.expire_all()
    tasks = get_pending_tasks(db, "original")
    assert [task.kind for task in tasks] == ["awaiting_response"]
    assert tasks[0].source_refs == [f"assignments:{assignment.id}"]
    assert tasks[0].derived
    assignment.status = "accepted"
    db.commit()
    db.expire_all()
    assert get_pending_tasks(db, "original") == []


@pytest.mark.parametrize("status", ["resolved", "cancelled", "guidance_only", "intake"])
def test_no_dispatch_tasks_for_closed_or_unfinished_cases(db, status):
    db.get(IncidentRow, "original").status = status
    db.commit()
    assert get_pending_tasks(db, "original") == []


def test_duplicate_does_not_create_another_assignment_task(db):
    assert get_pending_tasks(db, "duplicate") == []


def test_review_remains_explicit_when_acknowledgment_is_not_stored(db):
    db.get(IncidentRow, "original").metrics_json = {
        "guardrail": {"check_failed": True, "is_grounded": False, "is_safe": False}
    }
    db.commit()
    task = next(
        task for task in get_pending_tasks(db, "original") if task.kind == "human_review"
    )
    assert "acknowledgment is not recorded" in task.reason


def test_availability_is_not_a_claim_of_capacity(db):
    active = offer(db, "accepted")
    offer(db, "accepted", incident_id="unrelated")
    responders = get_available_responders(db)
    assert [row.responder_id for row in responders] == ["ready"]
    assert responders[0].active_assignment_ids == [active.id]
    assert "capacity is not recorded" in responders[0].availability_basis


def test_assignment_history_keeps_declines(db):
    first = offer(db, "declined")
    second = offer(db, "accepted")
    rows = get_assignments(db, "original")
    assert [row.assignment_id for row in rows] == [first.id, second.id]
    assert [row.status for row in rows] == ["declined", "accepted"]


def test_http_tools_and_unknown_incidents(db):
    def override():
        yield db

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app)
        for suffix in ["history", "assignments", "pending-tasks"]:
            assert client.get(f"/coordination/incidents/original/{suffix}").status_code == 200
            assert client.get(f"/coordination/incidents/missing/{suffix}").status_code == 404
        body = client.get("/coordination/available-responders").json()
        assert body[0]["responder_id"] == "ready"
        assert client.get("/coordination/incidents/original/pending-tasks").json()[0][
            "derived"
        ]
    finally:
        app.dependency_overrides.clear()
