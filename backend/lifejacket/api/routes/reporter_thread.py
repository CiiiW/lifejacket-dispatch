"""Reporter side of the thread with the rescue team.

    GET  /intake/{id}/messages   the thread, as the reporter sees it
    POST /intake/{id}/messages   write to the team (either side may start)
    GET  /intake/{id}/progress   which intake step is running, for the app's
                                 waiting line while a request is in flight
    POST /intake/my-reports      this device's reports: status and thread
                                 summary for every key it holds

Both require the `X-Reporter-Key` header holding the key `/intake/start`
returned. The incident ID alone is not enough: see
`services.reporter_thread`. Legacy routes; network mode blocks them.
"""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from lifejacket.models.coordinator import (
    MyReport,
    MyReportsRequest,
    ProgressOut,
    ReporterMessage,
    ReporterMessageIn,
)
from lifejacket.models.db import get_session
from lifejacket.services import progress, reporter_thread

router = APIRouter(prefix="/intake", tags=["intake (reporter)"])


@router.post("/my-reports", response_model=list[MyReport])
def my_reports(body: MyReportsRequest, session: Session = Depends(get_session)):
    """Every report whose key this device holds; unmatched keys are left out."""
    return reporter_thread.my_reports(session, body.reports)


@router.get("/{incident_id}/progress", response_model=ProgressOut)
def intake_progress(
    incident_id: str,
    session: Session = Depends(get_session),
    reporter_key: str | None = Header(default=None, alias="X-Reporter-Key"),
):
    reporter_thread.check_key(session, incident_id, reporter_key)
    return ProgressOut(step=progress.current(incident_id))


@router.get("/{incident_id}/messages", response_model=list[ReporterMessage])
def my_messages(
    incident_id: str,
    session: Session = Depends(get_session),
    reporter_key: str | None = Header(default=None, alias="X-Reporter-Key"),
):
    reporter_thread.check_key(session, incident_id, reporter_key)
    return reporter_thread.reporter_view(session, incident_id)


@router.post("/{incident_id}/messages", response_model=ReporterMessage)
def reply_to_team(
    incident_id: str,
    body: ReporterMessageIn,
    session: Session = Depends(get_session),
    reporter_key: str | None = Header(default=None, alias="X-Reporter-Key"),
):
    reporter_thread.check_key(session, incident_id, reporter_key)
    row = reporter_thread.post(session, incident_id, "reporter", body.body, None)
    session.commit()
    return reporter_thread.reporter_message(row)
