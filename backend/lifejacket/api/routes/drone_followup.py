"""Case-scoped queued AI screening and background reminder visibility."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifejacket.access.dependencies import AccessSession, current_access_session
from lifejacket.api.routes.drone_requests import enabled
from lifejacket.api.routes.network import private
from lifejacket.config import settings
from lifejacket.models.db import get_session
from lifejacket.models.drone_intake import Contract
from lifejacket.models.tables import CaseDroneAnalysisRow, CaseDroneReminderRow
from lifejacket.services import (
    drone_followup as common,
)
from lifejacket.services import (
    drone_frame_analysis as ai,
)
from lifejacket.services import (
    drone_reminders as reminders,
)
from lifejacket.services import (
    drone_requests as requests,
)


class QueueAnalysis(Contract):
    revision: int = Field(ge=0)
    confirmed: Literal[True]
    stage: Literal["detect", "assess"]
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    detection_job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    animal_index: int | None = Field(default=None, ge=0, le=31)

    @model_validator(mode="after")
    def target(self):
        if self.stage == "assess" and (
            self.detection_job_id is None or self.animal_index is None
        ):
            raise ValueError("Choose a detected animal")
        if self.stage == "detect" and (
            self.detection_job_id is not None or self.animal_index is not None
        ):
            raise ValueError("Detection does not accept an animal selection")
        return self


class RetryReminder(Contract):
    revision: int = Field(ge=0)
    confirmed: Literal[True]
    notification_id: str = Field(pattern=r"^[a-f0-9]{64}$")


router = APIRouter(
    prefix="/network/cases/{case_id}/drone-requests/{request_id}",
    tags=["drone follow-up"],
    dependencies=[Depends(enabled)],
)


@router.get("/analysis", dependencies=[Depends(ai.enabled)])
def listing(
    case_id: str,
    request_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    requests.access(db, current.access.principal, case_id)
    requests.get(db, case_id, request_id)
    rows = db.scalars(
        select(CaseDroneAnalysisRow)
        .where(CaseDroneAnalysisRow.request_id == request_id)
        .order_by(CaseDroneAnalysisRow.created_at.desc())
        .limit(100)
    ).all()
    return {
        "jobs": [ai.out(row) for row in rows],
        "worker": common.worker_status(db, "analysis"),
    }


@router.post(
    "/evidence/{evidence_id}/analysis", status_code=202, dependencies=[Depends(ai.enabled)]
)
def queue(
    case_id: str,
    request_id: str,
    evidence_id: str,
    body: QueueAnalysis,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    try:
        return ai.enqueue(db, current.access.principal, case_id, request_id, evidence_id, body)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Analysis request changed; refresh before retrying") from exc


@router.get("/reminders")
def reminder_status(
    case_id: str,
    request_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    _, case = requests.access(db, current.access.principal, case_id)
    requests.get(db, case_id, request_id)
    rows = db.scalars(
        select(CaseDroneReminderRow)
        .where(CaseDroneReminderRow.request_id == request_id)
        .order_by(CaseDroneReminderRow.created_at.desc())
        .limit(100)
    ).all()
    return {
        "enabled": settings.drone_reminders_enabled,
        "destination_configured": reminders.configured(case.lead_org_id),
        "worker": common.worker_status(db, "reminders"),
        "items": [reminders.out(row) for row in rows],
    }


@router.post("/reminders/retry", dependencies=[Depends(reminders.enabled)])
def reminder_retry(
    case_id: str,
    request_id: str,
    body: RetryReminder,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    return reminders.retry(db, current.access.principal, case_id, request_id, body)
