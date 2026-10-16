"""Read-only tools for a future coordination agent or an API consumer.

These functions retrieve evidence; they do not choose actions, send messages,
or approve dispatch. Pending tasks are inferred checks, not a stored task list.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lifejacket.models.coordination import (
    AssignmentRecord,
    AvailableResponder,
    HistoryEntry,
    IncidentHistory,
    PendingTask,
)
from lifejacket.models.schemas import AssignmentStatus, IncidentStatus
from lifejacket.models.tables import AssignmentRow, IncidentEventRow, IncidentRow, ResponderRow
from lifejacket.services.events import incident_state

ACTIVE_ASSIGNMENTS = (
    AssignmentStatus.ACCEPTED.value,
    AssignmentStatus.EN_ROUTE.value,
    AssignmentStatus.ON_SCENE.value,
)
CLOSED_INCIDENTS = (
    IncidentStatus.RESOLVED.value,
    IncidentStatus.CANCELLED.value,
    IncidentStatus.GUIDANCE_ONLY.value,
)
RESPONSE_INCIDENTS = (
    IncidentStatus.AWAITING_DISPATCH.value,
    IncidentStatus.DISPATCHED.value,
    IncidentStatus.ACCEPTED.value,
    IncidentStatus.EN_ROUTE.value,
    IncidentStatus.ON_SCENE.value,
)


def _incident(session: Session, incident_id: str) -> IncidentRow:
    row = session.get(IncidentRow, incident_id)
    if row is None:
        raise LookupError(f"Unknown incident: {incident_id}")
    return row


def _assignment_record(row: AssignmentRow) -> AssignmentRecord:
    return AssignmentRecord(
        assignment_id=row.id,
        incident_id=row.incident_id,
        responder_id=row.responder_id,
        responder_name=row.responder.name if row.responder else None,
        status=row.status,
        offered_at=row.offered_at,
        responded_at=row.responded_at,
        match_score=row.match_score,
        match_rationale=row.match_rationale,
        source_ref=f"assignments:{row.id}",
    )


def get_assignments(session: Session, incident_id: str) -> list[AssignmentRecord]:
    """All recorded offers and latest responses for one incident."""
    _incident(session, incident_id)
    rows = session.scalars(
        select(AssignmentRow)
        .options(selectinload(AssignmentRow.responder))
        .where(AssignmentRow.incident_id == incident_id)
        .order_by(AssignmentRow.offered_at, AssignmentRow.id)
    ).all()
    return [_assignment_record(row) for row in rows]


def get_incident_history(session: Session, incident_id: str) -> IncidentHistory:
    """Retrieve one incident and its directly linked duplicate evidence.

    Do not infer an event from `updated_at`: it cannot establish what changed.
    """
    incident = _incident(session, incident_id)
    root_id = incident.duplicate_of or incident_id
    root = _incident(session, root_id)
    reports = session.scalars(
        select(IncidentRow)
        .options(
            selectinload(IncidentRow.messages),
            selectinload(IncidentRow.photos),
            selectinload(IncidentRow.assignments).selectinload(AssignmentRow.responder),
            selectinload(IncidentRow.logs),
        )
        .where((IncidentRow.incident_id == root_id) | (IncidentRow.duplicate_of == root_id))
        .order_by(IncidentRow.created_at, IncidentRow.incident_id)
    ).all()
    entries = []
    for row in reports:
        entries.append(
            HistoryEntry(
                source_ref=f"incidents:{row.incident_id}",
                incident_id=row.incident_id,
                recorded_at=row.created_at,
                kind="report_snapshot",
                data={
                    "status": row.status,
                    "updated_at": row.updated_at.isoformat(),
                    "duplicate_of": row.duplicate_of,
                    "identification": row.identification_json,
                    "assessment": row.assessment_json,
                    "report": row.report_json,
                    "metrics": row.metrics_json,
                },
            )
        )
        for message in row.messages:
            entries.append(
                HistoryEntry(
                    source_ref=f"chat_messages:{message.id}",
                    incident_id=row.incident_id,
                    recorded_at=message.created_at,
                    kind="message",
                    data={
                        "role": message.role,
                        "content": message.content,
                        "agent_name": message.agent_name,
                        "feature": message.feature,
                    },
                )
            )
        for photo in row.photos:
            entries.append(
                HistoryEntry(
                    source_ref=f"photos:{photo.photo_id}",
                    incident_id=row.incident_id,
                    recorded_at=photo.uploaded_at,
                    kind="photo",
                    data={
                        "photo_id": photo.photo_id,
                        "captured_at": (
                            photo.exif_captured_at.isoformat()
                            if photo.exif_captured_at
                            else None
                        ),
                        "url": f"/incidents/{row.incident_id}/photos/{photo.photo_id}",
                    },
                )
            )
        for assignment in row.assignments:
            entries.append(
                HistoryEntry(
                    source_ref=f"assignments:{assignment.id}",
                    incident_id=row.incident_id,
                    recorded_at=assignment.offered_at,
                    kind="assignment_snapshot",
                    data=_assignment_record(assignment).model_dump(mode="json"),
                )
            )
        for log in row.logs:
            entries.append(
                HistoryEntry(
                    source_ref=f"incident_logs:{log.id}",
                    incident_id=row.incident_id,
                    recorded_at=log.created_at,
                    kind="closing_log",
                    data={
                        "responder_id": log.responder_id,
                        "confirmed_species": log.confirmed_species,
                        "outcome": log.outcome,
                        "actions_taken": log.actions_taken,
                        "notes": log.notes,
                    },
                )
            )
    recorded = session.scalars(
        select(IncidentEventRow)
        .where(IncidentEventRow.incident_id.in_([row.incident_id for row in reports]))
        .order_by(IncidentEventRow.recorded_at, IncidentEventRow.id)
    ).all()
    entries.extend(
        HistoryEntry(
            source_ref=f"incident_events:{event.id}",
            incident_id=event.incident_id,
            recorded_at=event.recorded_at,
            kind="recorded_event",
            data={
                "event_kind": event.kind,
                "actor_ref": event.actor_ref,
                "details": event.details,
                "timestamp_basis": "UTC",
            },
        )
        for event in recorded
    )
    entries.sort(key=lambda entry: (entry.recorded_at, entry.source_ref))
    return IncidentHistory(
        incident_id=root_id,
        status=root.status,
        assigned_responder_id=root.assigned_responder_id,
        duplicate_of=incident.duplicate_of,
        entries=entries,
    )


def get_pending_tasks(session: Session, incident_id: str) -> list[PendingTask]:
    """Derived coordination checks for one active, nonduplicate case."""
    incident = _incident(session, incident_id)
    if incident.status in CLOSED_INCIDENTS or incident.duplicate_of:
        return []
    tasks = []
    offers = [
        row for row in incident.assignments if row.status == AssignmentStatus.OFFERED.value
    ]
    accepted = [row for row in incident.assignments if row.status in ACTIVE_ASSIGNMENTS]
    if incident.status in RESPONSE_INCIDENTS and not accepted:
        if offers:
            tasks.append(
                PendingTask(
                    incident_id=incident_id,
                    kind="awaiting_response",
                    reason="An assignment was offered; no accepted assignment is recorded.",
                    source_refs=[f"assignments:{row.id}" for row in offers],
                )
            )
        else:
            tasks.append(
                PendingTask(
                    incident_id=incident_id,
                    kind="needs_assignment",
                    reason=(
                        "No offered or accepted assignment is recorded for this active case."
                    ),
                    source_refs=[f"incidents:{incident_id}"],
                )
            )
    if incident_state(incident)["requires_human_review"]:
        tasks.append(
            PendingTask(
                incident_id=incident_id,
                kind="human_review",
                reason=(
                    "The assessment or guardrail record requires human review; "
                    "acknowledgment is not recorded."
                ),
                source_refs=[f"incidents:{incident_id}"],
            )
        )
    return tasks


def get_available_responders(session: Session) -> list[AvailableResponder]:
    """On-duty active responders, with workload but no claim of spare capacity."""
    rows = session.scalars(
        select(ResponderRow)
        .options(selectinload(ResponderRow.assignments).selectinload(AssignmentRow.incident))
        .where(ResponderRow.is_active.is_(True), ResponderRow.is_on_duty.is_(True))
        .order_by(ResponderRow.responder_id)
    ).all()
    return [
        AvailableResponder(
            responder_id=row.responder_id,
            name=row.name,
            kind=row.kind,
            response_area=row.response_area,
            response_type=row.response_type,
            active_assignment_ids=sorted(
                assignment.id
                for assignment in row.assignments
                if assignment.status in ACTIVE_ASSIGNMENTS
                and assignment.incident.status not in CLOSED_INCIDENTS
            ),
            source_ref=f"responders:{row.responder_id}",
        )
        for row in rows
    ]
