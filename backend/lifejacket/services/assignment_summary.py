"""Keep a legacy primary assignment stable while other offers are answered.

Accepted legacy assignments are not automatically network support memberships.
Explicit organization participation will be added independently.
"""

from sqlalchemy import select

from lifejacket.models.tables import AssignmentRow

ACTIVE = {"accepted", "en_route", "on_scene"}
TERMINAL_CASES = {"resolved", "cancelled", "guidance_only"}


def refresh_assignment_summary(session, incident):
    session.flush()
    rows = list(
        session.scalars(
            select(AssignmentRow)
            .where(AssignmentRow.incident_id == incident.incident_id)
            .order_by(AssignmentRow.id)
        )
    )
    active = [row for row in rows if row.status in ACTIVE]
    current = next(
        (row for row in active if row.responder_id == incident.assigned_responder_id), None
    )
    if active:
        primary = current or active[0]
        preserve_progress = current is not None and incident.status in {"en_route", "on_scene"}
        incident.assigned_responder_id = primary.responder_id
        if not preserve_progress:
            incident.status = primary.status
    else:
        incident.assigned_responder_id = None
        incident.status = (
            "dispatched"
            if any(row.status == "offered" for row in rows)
            else "awaiting_dispatch"
        )
