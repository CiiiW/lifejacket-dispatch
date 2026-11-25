"""Local console: decide what happens to an incident, and talk to its reporter.

    GET  /incidents/{id}/volunteers        volunteers near the incident
    GET  /incidents/{id}/volunteer-alerts  alerts sent for it
    POST /incidents/{id}/volunteer-alerts  alert volunteers to check in
    POST /incidents/{id}/ignore            close it, with a reason
    POST /incidents/{id}/drone-survey      plan a simulated survey over it
    GET  /incidents/{id}/decisions         the decision log
    GET  /incidents/{id}/messages          the thread with the reporter
    POST /incidents/{id}/messages          write to the reporter

"Send a team" is the existing `POST /responders/assign`.

Legacy routes, like the rest of the local console: no sign-in, attributed to
the actor the client names. Network mode blocks every one of them.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lifejacket.models.coordinator import (
    AlertRequest,
    CoordinatorThread,
    DecisionEntry,
    DroneSurveyOut,
    DroneSurveyRequest,
    IgnoreRequest,
    IgnoreResult,
    MessageIn,
    NearbyVolunteers,
    ThreadMessage,
    VolunteerAlertOut,
)
from lifejacket.models.db import get_session
from lifejacket.services import coordinator_actions, reporter_thread, volunteers

router = APIRouter(prefix="/incidents", tags=["coordinator actions (local console)"])


@router.get("/{incident_id}/volunteers", response_model=NearbyVolunteers)
def nearby_volunteers(incident_id: str, session: Session = Depends(get_session)):
    return volunteers.nearby(session, volunteers.get_incident(session, incident_id))


@router.get("/{incident_id}/volunteer-alerts", response_model=list[VolunteerAlertOut])
def volunteer_alerts(incident_id: str, session: Session = Depends(get_session)):
    volunteers.get_incident(session, incident_id)
    return volunteers.list_alerts(session, incident_id)


@router.post("/{incident_id}/volunteer-alerts", response_model=list[VolunteerAlertOut])
def alert_volunteers(
    incident_id: str, body: AlertRequest, session: Session = Depends(get_session)
):
    incident = volunteers.get_incident(session, incident_id)
    sent = volunteers.send_alerts(
        session, incident, body.volunteer_ids, body.message, body.sent_by
    )
    session.commit()
    return sent


@router.post("/{incident_id}/ignore", response_model=IgnoreResult)
def ignore_incident(
    incident_id: str, body: IgnoreRequest, session: Session = Depends(get_session)
):
    incident = volunteers.get_incident(session, incident_id)
    result = coordinator_actions.ignore(
        session, incident, body.reason, body.note, body.decided_by
    )
    session.commit()
    return result


@router.post("/{incident_id}/drone-survey", response_model=DroneSurveyOut)
def drone_survey(
    incident_id: str, body: DroneSurveyRequest, session: Session = Depends(get_session)
):
    incident = volunteers.get_incident(session, incident_id)
    plan = coordinator_actions.plan_drone_survey(session, incident, body.requested_by)
    session.commit()
    return plan


@router.get("/{incident_id}/decisions", response_model=list[DecisionEntry])
def decisions(incident_id: str, session: Session = Depends(get_session)):
    volunteers.get_incident(session, incident_id)
    return coordinator_actions.decision_log(session, incident_id)


@router.get("/{incident_id}/messages", response_model=CoordinatorThread)
def thread(incident_id: str, session: Session = Depends(get_session)):
    volunteers.get_incident(session, incident_id)
    return reporter_thread.coordinator_view(session, incident_id)


@router.post("/{incident_id}/messages", response_model=ThreadMessage)
def message_reporter(
    incident_id: str, body: MessageIn, session: Session = Depends(get_session)
):
    volunteers.get_incident(session, incident_id)
    row = reporter_thread.post(session, incident_id, "coordinator", body.body, body.author_ref)
    session.commit()
    return ThreadMessage(
        message_id=row.id,
        sender="coordinator",
        body=row.body,
        author_ref=row.author_ref,
        created_at=volunteers.as_utc(row.created_at),
    )
