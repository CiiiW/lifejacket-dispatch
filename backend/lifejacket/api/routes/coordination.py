"""Thin HTTP adapters for the read-only coordination tools."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lifejacket.agents.coordination import CoordinationAgent
from lifejacket.llm.client import get_client
from lifejacket.models.coordination import (
    AssignmentRecord,
    AvailableResponder,
    CoordinationResult,
    IncidentHistory,
    PendingTask,
)
from lifejacket.models.db import get_session
from lifejacket.models.handover import ShiftHandover
from lifejacket.services import coordination
from lifejacket.services.handover import build_handover

router = APIRouter(prefix="/coordination", tags=["coordination tools"])


@router.get("/handover", response_model=ShiftHandover)
def handover(start: datetime, end: datetime, session: Session = Depends(get_session)):
    try:
        return build_handover(session, start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/incidents/{incident_id}/history", response_model=IncidentHistory)
def incident_history(
    incident_id: str, session: Session = Depends(get_session)
) -> IncidentHistory:
    try:
        return coordination.get_incident_history(session, incident_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/incidents/{incident_id}/assignments", response_model=list[AssignmentRecord])
def assignments(
    incident_id: str, session: Session = Depends(get_session)
) -> list[AssignmentRecord]:
    try:
        return coordination.get_assignments(session, incident_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/incidents/{incident_id}/pending-tasks", response_model=list[PendingTask])
def pending_tasks(
    incident_id: str, session: Session = Depends(get_session)
) -> list[PendingTask]:
    try:
        return coordination.get_pending_tasks(session, incident_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/available-responders", response_model=list[AvailableResponder])
def available_responders(session: Session = Depends(get_session)) -> list[AvailableResponder]:
    return coordination.get_available_responders(session)


@router.post("/incidents/{incident_id}/check", response_model=CoordinationResult)
def check_case(
    incident_id: str, session: Session = Depends(get_session)
) -> CoordinationResult:
    try:
        return CoordinationAgent(get_client()).run(session, incident_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
