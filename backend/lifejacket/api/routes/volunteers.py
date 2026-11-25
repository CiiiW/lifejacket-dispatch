"""Local console: the fictional volunteer roster and replies to alerts.

    GET  /volunteers/summary                 how many, how many available
    POST /volunteers/seed-demo               load the fictional volunteers
    POST /volunteers/alerts/{id}/reply       record a volunteer's answer

There is deliberately no endpoint that lists every volunteer: the console
sees volunteers only near a selected incident (`/incidents/{id}/volunteers`).
Legacy routes; network mode blocks them.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lifejacket.models.coordinator import AlertReply, VolunteerAlertOut, VolunteerSummary
from lifejacket.models.db import get_session
from lifejacket.services import volunteers

router = APIRouter(prefix="/volunteers", tags=["volunteers (local console)"])


@router.get("/summary", response_model=VolunteerSummary)
def summary(session: Session = Depends(get_session)):
    return volunteers.summary(session)


@router.post("/seed-demo", response_model=VolunteerSummary)
def seed_demo(session: Session = Depends(get_session)):
    result = volunteers.seed_demo_volunteers(session)
    session.commit()
    return result


@router.post("/alerts/{alert_id}/reply", response_model=VolunteerAlertOut)
def reply(alert_id: int, body: AlertReply, session: Session = Depends(get_session)):
    result = volunteers.record_reply(
        session, alert_id, body.status, body.note, body.recorded_by
    )
    session.commit()
    return result
