"""Transactional request lifecycle. No aircraft commands, alerts or auto-triage."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select, update

from lifejacket.access.policy import Role, can_update_case, participating_org
from lifejacket.api.routes.network_actions import context
from lifejacket.config import settings
from lifejacket.models.tables import (
    CaseDroneEventRow,
    CaseDroneEvidenceRow,
    CaseDroneRequestRow,
    IncidentRow,
)
from lifejacket.services.drone_suggestions import suggest

TRANSITIONS = {
    "requested": ["approved", "declined", "cancelled"],
    "approved": ["in_progress", "cancelled", "failed"],
    "in_progress": ["evidence_ready", "cancelled", "failed"],
    "evidence_ready": ["reviewed", "cancelled", "failed"],
}


def now():
    return datetime.now(UTC).replace(tzinfo=None)


def access(session, actor, case_id, write=False):
    scope, case, _ = context(session, actor, case_id)
    if not participating_org(actor, case):
        raise HTTPException(403, "Drone request access requires case participation")
    if write and not (
        can_update_case(actor, case)
        and actor.role == Role.CENTER_COORDINATOR
        and actor.organization_id == case.lead_org_id
    ):
        raise HTTPException(403, "Only the active case lead coordinator manages requests")
    return scope, case


def get(session, case_id, request_id):
    row = session.get(CaseDroneRequestRow, request_id)
    if row is None or row.incident_id != case_id:
        raise HTTPException(404, "Drone request unavailable")
    return row


def out(row, writable=False):
    return {
        "request_id": row.request_id,
        "case_id": row.incident_id,
        "status": row.status,
        "revision": row.revision,
        "created_at": row.created_at.isoformat() + "Z",
        **row.payload_json,
        "allowed_transitions": TRANSITIONS.get(row.status, []) if writable else [],
    }


def writable(actor, case):
    return (
        can_update_case(actor, case)
        and actor.role == Role.CENTER_COORDINATOR
        and actor.organization_id == case.lead_org_id
    )


def event(session, row, actor, kind, details):
    session.add(
        CaseDroneEventRow(
            event_id=uuid.uuid4().hex,
            request_id=row.request_id,
            revision=row.revision,
            actor_user_id=actor.user_id,
            organization_id=actor.organization_id,
            kind=kind,
            details_json=details,
            recorded_at=now(),
        )
    )


def compare_swap(session, row, revision, **values):
    if row.revision != revision:
        raise HTTPException(409, "Request changed; refresh before retrying")
    changed = session.execute(
        update(CaseDroneRequestRow)
        .where(
            CaseDroneRequestRow.request_id == row.request_id,
            CaseDroneRequestRow.revision == revision,
        )
        .values(revision=revision + 1, **values),
        execution_options={"synchronize_session": False},
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Request changed; refresh before retrying")
    session.expire(row)
    session.refresh(row)


def suggestions(session, case_id, case):
    if not case.active:
        return []
    active = session.scalars(
        select(CaseDroneRequestRow).where(
            CaseDroneRequestRow.incident_id == case_id,
            CaseDroneRequestRow.status.in_(TRANSITIONS),
        )
    ).all()
    if any(row.payload_json.get("purpose") == "verification" for row in active):
        return []
    incident = session.get(IncidentRow, case_id)
    item = suggest(incident, settings.drone_verification_confidence_threshold)
    if item is None:
        return []
    consumed = session.scalar(
        select(CaseDroneRequestRow.request_id)
        .where(
            CaseDroneRequestRow.incident_id == case_id,
            CaseDroneRequestRow.request_key == item["suggestion_id"],
        )
        .limit(1)
    )
    return [] if consumed else [item]


def create(session, actor, case_id, body):
    _, case = access(session, actor, case_id, write=True)
    effective_key = body.suggestion_id or body.request_key
    previous = session.scalar(
        select(CaseDroneRequestRow).where(
            CaseDroneRequestRow.incident_id == case_id,
            CaseDroneRequestRow.request_key == effective_key,
        )
    )
    payload = body.model_dump(mode="json", exclude={"request_key"})
    if previous:
        if previous.payload_json["original_request"] != payload:
            raise HTTPException(409, "Request key was already used for different details")
        return out(previous, True)
    suggestion = None
    if body.suggestion_id:
        suggestion = next(
            (
                s
                for s in suggestions(session, case_id, case)
                if s["suggestion_id"] == body.suggestion_id
            ),
            None,
        )
        if suggestion is None or body.purpose != "verification":
            raise HTTPException(409, "Suggestion changed; refresh and review current evidence")
    incident = session.get(IncidentRow, case_id)
    row = CaseDroneRequestRow(
        request_id=uuid.uuid4().hex,
        incident_id=case_id,
        request_key=effective_key,
        status="requested",
        revision=0,
        payload_json={
            **payload,
            "original_request": payload,
            "suggestion_snapshot": suggestion,
            "target_location": {
                "latitude": incident.latitude,
                "longitude": incident.longitude,
                "reported_at": incident.created_at.isoformat(),
            },
            "operator": None,
            "outcome": None,
        },
        created_at=now(),
    )
    session.add(row)
    session.flush()
    event(session, row, actor, "requested", {"reason": body.reason})
    session.commit()
    return out(row, True)


def change(session, actor, case_id, request_id, body):
    access(session, actor, case_id, write=True)
    row = get(session, case_id, request_id)
    if body.status not in TRANSITIONS.get(row.status, []):
        raise HTTPException(409, "This request transition is unavailable")
    payload = dict(row.payload_json)
    if body.status == "approved":
        if not body.operator:
            raise HTTPException(422, "Assign a responsible operator")
        payload["operator"] = body.operator
    elif body.operator is not None:
        raise HTTPException(422, "Assign the operator when approving")
    if body.status == "in_progress" and payload["execution_kind"] == "operator_flight":
        if not body.feasibility_confirmed:
            raise HTTPException(422, "Operator must confirm flight feasibility")
    if body.status in {"evidence_ready", "reviewed"}:
        if (
            session.scalar(
                select(CaseDroneEvidenceRow.evidence_id)
                .where(
                    CaseDroneEvidenceRow.request_id == request_id,
                )
                .limit(1)
            )
            is None
        ):
            raise HTTPException(409, "Attach evidence before submitting for review")
    if body.status == "reviewed":
        if body.outcome is None:
            raise HTTPException(422, "Record whether the objective was answered")
        payload["outcome"] = body.outcome
        payload["review_note"] = body.note
        # A review is an explicit addendum, not a replacement of intake findings.
        payload["reassessment"] = {
            "finding": body.note,
            "outcome": body.outcome,
            "reviewed_by": actor.user_id,
            "reviewed_at": now().isoformat() + "Z",
        }
        if body.next_review_at and body.next_review_at <= datetime.now(UTC):
            raise HTTPException(422, "Choose a future review time")
        if body.next_review_at:
            payload["next_review_at"] = body.next_review_at.isoformat()
    elif body.outcome is not None or body.next_review_at is not None:
        raise HTTPException(422, "Outcome and next review time belong to evidence review")
    compare_swap(session, row, body.revision, status=body.status, payload_json=payload)
    event(
        session,
        row,
        actor,
        body.status,
        {
            "note": body.note,
            "outcome": body.outcome,
            "feasibility_confirmed": body.feasibility_confirmed,
        },
    )
    session.commit()
    return out(row, True)
