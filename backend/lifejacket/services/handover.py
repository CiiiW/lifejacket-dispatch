"""Bounded, evidence-backed handover. No model or external actions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lifejacket.models.handover import CarryoverCase, RecordedEvent, ShiftHandover
from lifejacket.models.tables import IncidentEventRow, IncidentRow
from lifejacket.services.coordination import CLOSED_INCIDENTS, get_pending_tasks

EVENT_LIMIT = 500
CASE_LIMIT = 200


def event_record(row: IncidentEventRow) -> RecordedEvent:
    return RecordedEvent(
        event_id=row.id,
        incident_id=row.incident_id,
        recorded_at=row.recorded_at.replace(tzinfo=UTC),
        kind=row.kind,
        actor_ref=row.actor_ref,
        details=row.details,
        source_ref=f"incident_events:{row.id}",
    )


def build_handover(session: Session, start: datetime, end: datetime) -> ShiftHandover:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Start and end must include a timezone offset.")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end <= start or end - start > timedelta(days=7):
        raise ValueError("Choose a positive window of at most seven days.")
    rows = session.scalars(
        select(IncidentEventRow)
        .where(
            IncidentEventRow.recorded_at >= start.replace(tzinfo=None),
            IncidentEventRow.recorded_at < end.replace(tzinfo=None),
        )
        .order_by(IncidentEventRow.recorded_at, IncidentEventRow.id)
        .limit(EVENT_LIMIT + 1)
    ).all()
    cases = session.scalars(
        select(IncidentRow)
        .options(
            selectinload(IncidentRow.assignments),
        )
        .where(
            IncidentRow.status.not_in(CLOSED_INCIDENTS),
            IncidentRow.duplicate_of.is_(None),
        )
        .order_by(IncidentRow.incident_id)
        .limit(CASE_LIMIT + 1)
    ).all()
    return ShiftHandover(
        start=start,
        end=end,
        generated_at=datetime.now(UTC),
        changes=[event_record(row) for row in rows[:EVENT_LIMIT]],
        current_carryover=[
            CarryoverCase(
                incident_id=row.incident_id,
                headline=row.report_headline or row.species_common_name,
                status=row.status,
                severity_level=row.severity_level,
                assigned_responder_id=row.assigned_responder_id,
                tasks=get_pending_tasks(session, row.incident_id),
                source_ref=f"incidents:{row.incident_id}",
            )
            for row in cases[:CASE_LIMIT]
        ],
        changes_truncated=len(rows) > EVENT_LIMIT,
        carryover_truncated=len(cases) > CASE_LIMIT,
        limitations=[
            "Changes use recorded UTC times in [start, end); no historical backfill.",
            "Carryover is the current snapshot at generation, not state at shift end.",
            "Older cases and direct database writes may have no recorded events.",
            "Actor references are caller-supplied, not authenticated identities.",
            "Installation-wide scope; no center-specific authorization exists yet.",
            "Pending checks are derived, not assigned tasks or review acknowledgments.",
        ],
    )
