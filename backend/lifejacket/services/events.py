"""Explicit event writes participate in the caller's transaction."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from lifejacket.models.tables import IncidentEventRow, IncidentRow
from lifejacket.services.health import needs_review


def incident_state(row: IncidentRow) -> dict:
    assessment = row.assessment_json or {}
    metrics = row.metrics_json or {}
    guardrail = metrics.get("guardrail") or {}
    return {
        "status": row.status,
        "assigned_responder_id": row.assigned_responder_id,
        "duplicate_of": row.duplicate_of,
        "severity_level": row.severity_level,
        "requires_human_review": bool(
            assessment.get("requires_human_review")
            or guardrail.get("check_failed")
            or (
                guardrail
                and (not guardrail.get("is_grounded") or not guardrail.get("is_safe"))
            )
            or needs_review(metrics)
        ),
    }


def record_event(
    session: Session,
    incident_id: str,
    kind: str,
    details: dict,
    actor_ref: str | None = None,
) -> None:
    session.add(
        IncidentEventRow(
            incident_id=incident_id,
            recorded_at=datetime.now(UTC).replace(tzinfo=None),
            kind=kind,
            actor_ref=actor_ref,
            details=details,
        )
    )


def record_incident_change(
    session: Session,
    row: IncidentRow,
    before: dict | None,
    actor_ref: str | None = None,
) -> None:
    after = incident_state(row)
    if before is None:
        record_event(session, row.incident_id, "incident_created", {"state": after}, actor_ref)
    elif before != after:
        record_event(
            session,
            row.incident_id,
            "incident_changed",
            {
                "changes": {
                    key: {"before": before[key], "after": value}
                    for key, value in after.items()
                    if before[key] != value
                }
            },
            actor_ref,
        )
