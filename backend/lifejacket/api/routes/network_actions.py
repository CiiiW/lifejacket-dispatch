"""Human-confirmed response changes and current-case reporter contact only."""

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifejacket.access.cases import professional_query
from lifejacket.access.dependencies import AccessSession, current_access_session
from lifejacket.access.memberships import audit
from lifejacket.access.policy import CaseAccess, Role, can_contact_reporter, can_update_case
from lifejacket.access.reporter_view import ResponsePhase
from lifejacket.api.routes.network import private
from lifejacket.config import settings
from lifejacket.models.db import get_session
from lifejacket.models.tables import (
    NetworkCaseAssigneeRow,
    NetworkCaseOrganizationRow,
    NetworkCaseRow,
    NetworkResponseEventRow,
    NetworkResponseRow,
    ReporterDraftRow,
)

router = APIRouter(prefix="/network/cases", tags=["restricted response actions"])
NEXT = {
    "received": "accepted",
    "accepted": "en_route",
    "en_route": "on_scene",
    "on_scene": "animal_located",
}


def context(session, actor, incident_id):
    pair = session.execute(
        professional_query(actor).where(NetworkCaseRow.incident_id == incident_id)
    ).first()
    if not pair:
        raise HTTPException(404, "Case unavailable")
    _, row = pair
    if not row.verified_at or not row.verified_by or not row.verified_by.strip():
        raise HTTPException(409, "Case response scope needs review")
    relations = session.scalars(
        select(NetworkCaseOrganizationRow).where(
            NetworkCaseOrganizationRow.incident_id == incident_id,
            NetworkCaseOrganizationRow.accepted.is_(True),
        )
    ).all()
    assigned = session.scalars(
        select(NetworkCaseAssigneeRow.user_id).where(
            NetworkCaseAssigneeRow.incident_id == incident_id,
            NetworkCaseAssigneeRow.organization_id == actor.organization_id,
            NetworkCaseAssigneeRow.accepted.is_(True),
        )
    ).all()
    reporter = session.get(ReporterDraftRow, incident_id)
    valid_reporter = bool(
        reporter
        and reporter.submitted_at
        and reporter.submitted_user_id == row.reporter_user_id
    )
    channels = (
        {"phone" if item == "call" else item for item in reporter.contact_channels}
        if valid_reporter
        else set()
    )
    case = CaseAccess(
        case_id=incident_id,
        reporter_user_id=row.reporter_user_id,
        submitted=row.submitted,
        state_code=row.state_code,
        state_verified=True,
        active=row.response_phase != "closed",
        lead_org_id=row.lead_org_id,
        accepted_support_org_ids=frozenset(
            r.organization_id for r in relations if r.kind == "supporting"
        ),
        confirmed_receiving_org_id=actor.organization_id
        if any(
            r.kind == "receiving" and r.organization_id == actor.organization_id
            for r in relations
        )
        else None,
        accepted_assignee_user_ids=frozenset(assigned),
        reporter_contact_channels=frozenset(channels),
    )
    return row, case, reporter if valid_reporter else None


def enabled():
    if not settings.network_auth_enabled or not settings.network_case_actions_enabled:
        raise HTTPException(503, "Response actions are not configured")


def transitions(actor, case, phase):
    if not can_update_case(actor, case):
        return []
    allowed = [NEXT[phase]] if phase in NEXT else []
    if actor.role == Role.CENTER_COORDINATOR and actor.organization_id == case.lead_org_id:
        allowed.append("closed")
    return allowed


def snapshot(session, actor, row, case, reporter):
    try:
        ResponsePhase(row.response_phase)
    except ValueError as exc:
        raise HTTPException(409, "Case response needs review") from exc
    reasons = {"no_response_needed", "transferred"}
    if row.response_phase == "on_scene":
        reasons.add("unable_to_locate")
    if row.response_phase == "animal_located":
        reasons.add("rescue_complete")
    state = session.get(NetworkResponseRow, row.incident_id)
    return {
        "case_id": row.incident_id,
        "phase": row.response_phase,
        "revision": state.revision if state else 0,
        "allowed_transitions": transitions(actor, case, row.response_phase),
        "contact_channels": [
            channel
            for channel in ["phone", "text"]
            if reporter and can_contact_reporter(actor, case, channel)
        ],
        "closure_reasons": sorted(reasons)
        if "closed" in transitions(actor, case, row.response_phase)
        else [],
    }


@router.get("/{incident_id}/response", dependencies=[Depends(enabled)])
def read_response(
    incident_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    actor = current.access.principal
    row, case, reporter = context(session, actor, incident_id)
    return snapshot(session, actor, row, case, reporter)


class ResponseChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    phase: Literal["accepted", "en_route", "on_scene", "animal_located", "closed"]
    confirmed: Literal[True]
    closure_reason: (
        Literal["rescue_complete", "unable_to_locate", "no_response_needed", "transferred"]
        | None
    ) = None


@router.patch("/{incident_id}/response", dependencies=[Depends(enabled)])
def change_response(
    incident_id: str,
    body: ResponseChange,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    actor = current.access.principal
    row, case, reporter = context(session, actor, incident_id)
    if not can_update_case(actor, case):
        raise HTTPException(403, "Case response update not permitted")
    if body.phase not in transitions(actor, case, row.response_phase):
        raise HTTPException(409, "Refresh the case before changing its response")
    if body.phase == "closed":
        if not body.closure_reason:
            raise HTTPException(422, "Choose a closure reason")
        if body.closure_reason == "unable_to_locate" and row.response_phase != "on_scene":
            raise HTTPException(
                409, "Record arrival and the search before closing as unable to locate"
            )
        if body.closure_reason == "rescue_complete" and row.response_phase != "animal_located":
            raise HTTPException(
                409, "Confirm the animal was located before completing a rescue"
            )
    elif body.closure_reason is not None:
        raise HTTPException(422, "Closure reason is only used when closing")
    state = session.get(NetworkResponseRow, incident_id)
    if not state:
        state = NetworkResponseRow(incident_id=incident_id, revision=0)
        session.add(state)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "Case response changed; refresh before retrying") from exc
    if state.revision != body.revision:
        raise HTTPException(409, "Case response changed; refresh before retrying")
    previous = row.response_phase
    changed = session.execute(
        update(NetworkResponseRow)
        .where(
            NetworkResponseRow.incident_id == incident_id,
            NetworkResponseRow.revision == body.revision,
        )
        .values(revision=body.revision + 1)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Case response changed; refresh before retrying")
    row.response_phase = body.phase
    session.add(
        NetworkResponseEventRow(
            event_id="rsp_" + uuid.uuid4().hex,
            incident_id=incident_id,
            revision=body.revision + 1,
            previous_phase=previous,
            phase=body.phase,
            actor_user_id=actor.user_id,
            organization_id=actor.organization_id,
            closure_reason=body.closure_reason,
            recorded_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.commit()
    row, case, reporter = context(session, actor, incident_id)
    return snapshot(session, actor, row, case, reporter)


@router.get("/{incident_id}/reporter-contact", dependencies=[Depends(enabled)])
def contact(
    incident_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    actor = current.access.principal
    row, case, reporter = context(session, actor, incident_id)
    channels = [c for c in ["phone", "text"] if can_contact_reporter(actor, case, c)]
    if (
        not reporter
        or not channels
        or not reporter.phone_number
        or not re.fullmatch(r"\+[1-9][0-9]{7,14}", reporter.phone_number)
    ):
        raise HTTPException(403, "Current-case reporter contact is not permitted")
    audit(
        session,
        "reporter_contact_viewed",
        incident_id,
        actor.user_id,
        {"organization_id": actor.organization_id, "channels": channels},
    )
    session.commit()
    return {
        "case_id": row.incident_id,
        "phone_number": reporter.phone_number,
        "channels": channels,
        "presence": reporter.presence,
    }
