"""Restricted authenticated case discovery and minimal reporter updates."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifejacket.access.cases import case_card, professional_query, reporter_case
from lifejacket.access.dependencies import AccessSession, current_access_session
from lifejacket.access.reporter_view import ResponsePhase, reporter_update
from lifejacket.models.db import get_session
from lifejacket.models.tables import IncidentRow, NetworkCaseRow

router = APIRouter(prefix="/network", tags=["restricted network cases"])


class CaseCard(BaseModel):
    incident_id: str
    status: str
    state_code: str | None
    latitude: float | None
    longitude: float | None
    animal_group: str | None
    species_common_name: str | None
    severity_level: str | None
    lead_organization_id: str | None
    created_at: datetime


def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization, X-LifeJacket-Organization"


@router.get("/cases", response_model=list[CaseCard])
def list_cases(
    response: Response,
    scope: Literal[
        "all_allowed", "my_center", "assigned_to_me", "leading", "supporting", "receiving"
    ] = "all_allowed",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    query = (
        professional_query(current.access.principal, scope)
        .order_by(IncidentRow.created_at.desc(), IncidentRow.incident_id)
        .offset(offset)
        .limit(limit)
    )
    return [case_card(incident, access) for incident, access in session.execute(query)]


@router.get("/cases/{incident_id}", response_model=CaseCard)
def get_case(
    incident_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    pair = session.execute(
        professional_query(current.access.principal).where(
            IncidentRow.incident_id == incident_id
        )
    ).first()
    if pair is None:
        raise HTTPException(404, "Case unavailable")
    return case_card(*pair)


@router.get("/reports/{incident_id}")
def own_report(
    incident_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    # Ownership is an explicit reviewed account binding, never legacy reporter_id.
    access = session.scalar(
        select(NetworkCaseRow)
        .join(IncidentRow)
        .where(
            NetworkCaseRow.incident_id == incident_id,
            NetworkCaseRow.submitted.is_(True),
            NetworkCaseRow.reporter_user_id == current.access.principal.user_id,
            NetworkCaseRow.verified_at.is_not(None),
            NetworkCaseRow.verified_by.is_not(None),
            NetworkCaseRow.verified_by != "",
        )
    )
    if access is None:
        raise HTTPException(404, "Case unavailable")
    try:
        phase = ResponsePhase(access.response_phase)
    except ValueError as exc:
        raise HTTPException(409, "Case response update needs review") from exc
    return reporter_update(
        current.access.principal,
        reporter_case(current.access.principal, access),
        phase,
        now=datetime.now(UTC),
    )
