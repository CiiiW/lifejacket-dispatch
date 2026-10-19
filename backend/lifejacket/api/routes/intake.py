"""Reporter-facing endpoints: the intake conversation.

The flow a phone client follows:

    POST /intake/start                 -> incident_id, first prompt
    POST /intake/{id}/photo            -> upload a photo (repeatable)
    POST /intake/{id}/location         -> share GPS; triggers tide/weather
    POST /intake/{id}/reply            -> answer a question; returns the next one
    POST /intake/{id}/contact          -> phone number, so a team can call back
    POST /intake/{id}/retry            -> try the last step again after a failure
    GET  /intake/{id}                  -> current state, for resuming

Every mutating endpoint returns the same `TurnResponse` shape, so the client
has one rendering path regardless of which call produced the turn.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lifejacket.api.conditions import ConditionsOut, build_conditions
from lifejacket.chatbot.session import StepAction
from lifejacket.config import settings
from lifejacket.llm.client import ImageInput
from lifejacket.models import repository
from lifejacket.models.db import get_session
from lifejacket.models.schemas import AnimalDetection, ConversationStage, GeoPoint, Incident
from lifejacket.models.tables import IncidentRow, PhotoRow
from lifejacket.services import health
from lifejacket.services.pipeline import (
    SERVICE_RETRY_MESSAGE,
    IntakePipeline,
    TurnResult,
    reporter_closing_note,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intake", tags=["intake (reporter)"])

#: Accepted upload types. Restricted because the vision model needs a real
#: photograph, and an unexpected type fails deep inside the model call.
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/heic", "image/webp"}

#: Phone photos are a few megabytes; 15 MB leaves room for a high-end camera
#: while rejecting anything that is not plausibly a single photo.
MAX_PHOTO_BYTES = 15 * 1024 * 1024


class StartRequest(BaseModel):
    reporter_id: str | None = None
    #: Optional, so a report can be filed without handing over a phone number.
    #: Responders often need to call back, so the app should encourage it.
    reporter_phone: str | None = None


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = None
    source: str = "device_gps"


class ReplyRequest(BaseModel):
    text: str


class AnimalChoiceRequest(BaseModel):
    number: int = Field(ge=1)


class ContactRequest(BaseModel):
    #: Free text rather than a validated phone number: formats vary by country
    #: and a rejected number helps nobody. A responder dials what is here.
    #: Empty clears it.
    phone: str = ""


class ReporterTeam(BaseModel):
    """A rescue team the report was routed to, as the reporter sees it.

    Deliberately thinner than `DispatchCandidate`: no score, no capability
    list, no direct phone. A reporter does not need to see teams ranked
    against each other, and should not be ringing a stranding network
    directly -- the coordinator decides who attends.
    """

    name: str
    distance_km: float | None = None
    eta_minutes: float | None = None


class TurnResponse(BaseModel):
    """One turn of the conversation, as the client renders it."""

    incident_id: str
    message: str | None = None
    options: list[str] = Field(default_factory=list)
    awaiting_reply: bool = False
    complete: bool = False
    action: str | None = None
    stage: str
    questions_asked: int = 0
    #: What the animal has been identified as so far, e.g. "Oceanic dolphins".
    identified_as: str | None = None
    #: species / genus / family / group.
    taxon_rank: str | None = None
    #: Pooled confidence in `identified_as`, so the app can show how firm the
    #: answer is rather than presenting a 0.30 guess like a certainty.
    species_confidence: float | None = None

    #: Triage band, available as soon as the assessment agent has run rather
    #: than only at the end. It can still change while questions continue, so
    #: a client must label it provisional until `complete`.
    severity_level: str | None = None
    severity_score: float | None = None
    #: Why triage landed where it did, one plain sentence per rule that fired.
    #: Produced by the deterministic scorer, so these are the actual reasons,
    #: which is what makes them safe to show a reporter.
    severity_reasons: list[str] = Field(default_factory=list)
    #: How tide, weather and daylight shaped the recommendation.
    environmental_rationale: str | None = None
    #: One line on the animal's physical condition.
    injury_summary: str | None = None
    #: What the system recommends happens -- dispatch, monitor, guidance only.
    recommended_action: str | None = None
    #: Reporter-facing advice, as soon as the assessment produces it.
    safety_guidance: str | None = None
    reporter_instructions: list[str] = Field(default_factory=list)
    #: How the report ends, on its own rather than as the tail of the closing
    #: paragraph, so the app can render it as its own card.
    closing_note: str | None = None

    #: Teams whose coverage matched this incident, populated once intake
    #: finishes. These have NOT been contacted -- the report goes to the
    #: area's coordinators, who decide who attends.
    matched_teams: list[ReporterTeam] = Field(default_factory=list)

    report_headline: str | None = None
    #: Weather, tide, and daylight at the reporter's location, available from
    #: the moment they share it.
    conditions: ConditionsOut | None = None
    #: True when this turn is an apology for a model failure rather than a
    #: real step (`action` is then "service_retry"). The client should offer
    #: "Try again", which calls POST /intake/{id}/retry.
    service_error: bool = False
    detections: list[AnimalDetection] = Field(default_factory=list)
    detection_photo_id: str | None = None
    detection_photo_url: str | None = None
    detection_status: str = "pending"
    selected_detection: int | None = None


@router.post("/start", response_model=TurnResponse)
def start_intake(
    body: StartRequest, session: Session = Depends(get_session)
) -> TurnResponse:
    """Begin a new report. Returns the first prompt (asking for a photo)."""
    pipeline = IntakePipeline(session)
    incident, state = pipeline.start_incident(
        reporter_id=body.reporter_id, reporter_phone=body.reporter_phone
    )

    turn = pipeline.advance(incident, state)
    _persist(session, pipeline, incident, state)
    return _to_response(incident.incident_id, turn, state, incident)


@router.post("/{incident_id}/photo", response_model=TurnResponse)
async def upload_photo(
    incident_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> TurnResponse:
    """Attach a photo and advance the conversation.

    The image bytes are written to disk and the identification agent is given
    them directly from memory on this request, so the first identification pass
    happens without a second round trip.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type '{file.content_type}'. "
            f"Expected one of: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Photo is {len(data) / 1e6:.1f} MB; the limit is "
            f"{MAX_PHOTO_BYTES / 1e6:.0f} MB.",
        )

    incident, state, pipeline = _load(session, incident_id)
    if state.stage is ConversationStage.COMPLETE:
        raise HTTPException(
            status_code=409,
            detail="This report is complete; start a new report for another photo.",
        )

    photo_row = repository.save_photo(
        session,
        incident_id=incident_id,
        storage_path="",  # set below, once we know the generated photo_id
        content_type=file.content_type,
    )
    # Name the file after its photo_id so a file on disk can always be traced
    # back to its row, and vice versa.
    destination = settings.photo_storage_dir / f"{photo_row.photo_id}.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    photo_row.storage_path = str(destination)

    pipeline.attach_photo(incident, state, photo_row.photo_id)

    turn = pipeline.advance(
        incident,
        state,
        images=[
            ImageInput(data=data, mime_type=file.content_type, photo_id=photo_row.photo_id)
        ],
    )
    _persist(session, pipeline, incident, state)
    return _to_response(incident_id, turn, state, incident)


@router.post("/{incident_id}/location", response_model=TurnResponse)
def set_location(
    incident_id: str, body: LocationRequest, session: Session = Depends(get_session)
) -> TurnResponse:
    """Share the reporter's location.

    This is the call that triggers the tide, weather, and reverse-geocoding
    lookups, so it is the slowest endpoint in the intake flow -- roughly a
    second, since the three run concurrently.
    """
    incident, state, pipeline = _load(session, incident_id)

    pipeline.set_location(
        incident,
        state,
        GeoPoint(
            latitude=body.latitude,
            longitude=body.longitude,
            accuracy_meters=body.accuracy_meters,
            source=body.source,
        ),
    )

    turn = pipeline.advance(incident, state, images=_load_images(session, state))
    _persist(session, pipeline, incident, state)
    return _to_response(incident_id, turn, state, incident)


@router.post("/{incident_id}/contact", response_model=dict)
def set_contact(
    incident_id: str, body: ContactRequest, session: Session = Depends(get_session)
) -> dict:
    """Attach a phone number so a rescue team can call the reporter back.

    Separate from `/start` on purpose. Intake begins the moment the app opens,
    with no form to fill in, because someone standing over a dying animal
    should not be typing their number first. This lets them add it at any
    point afterwards -- including after the report is filed, which is when
    most people think of it.

    Sending an empty string clears the number, so a reporter can withdraw it.
    """
    row = session.get(IncidentRow, incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")

    phone = (body.phone or "").strip()
    row.reporter_phone = phone or None
    row.updated_at = datetime.now()
    session.commit()

    return {"incident_id": incident_id, "reporter_phone": row.reporter_phone}


@router.post("/{incident_id}/reply", response_model=TurnResponse)
def submit_reply(
    incident_id: str, body: ReplyRequest, session: Session = Depends(get_session)
) -> TurnResponse:
    """Answer the outstanding question and get the next turn."""
    incident, state, pipeline = _load(session, incident_id)

    # Any text is accepted: options are shortcuts for tapping, not a whitelist.
    # The agent reads the reply in context, so "the left one, I think" is fine.
    pipeline.submit_reply(incident, state, body.text)

    turn = pipeline.advance(incident, state, images=_load_images(session, state))
    _persist(session, pipeline, incident, state)
    return _to_response(incident_id, turn, state, incident)


@router.post("/{incident_id}/animal", response_model=TurnResponse)
def choose_animal(
    incident_id: str, body: AnimalChoiceRequest, session: Session = Depends(get_session)
) -> TurnResponse:
    """Choose or change the animal in the active photo during intake."""
    incident, state, pipeline = _load(session, incident_id)
    if state.stage is ConversationStage.COMPLETE:
        raise HTTPException(status_code=409, detail="This report is complete.")
    if state.detections is None or len(state.detections) < 2:
        raise HTTPException(
            status_code=409, detail="There is no animal choice for this photo."
        )
    if body.number > len(state.detections):
        raise HTTPException(status_code=422, detail="Animal number is out of range.")
    if state.selected_detection == body.number - 1:
        return get_state(incident_id, session)
    pipeline.select_animal(incident, state, body.number)
    turn = pipeline.advance(incident, state, images=_load_images(session, state))
    _persist(session, pipeline, incident, state)
    return _to_response(incident_id, turn, state, incident)


@router.post("/{incident_id}/retry", response_model=TurnResponse)
def retry_step(incident_id: str, session: Session = Depends(get_session)) -> TurnResponse:
    """Run the pending step again, without adding anything to the conversation.

    For the "Try again" button shown after a `service_error` turn. The
    conversation state was saved untouched when the step failed, so this simply
    re-runs it. Safe to call at any time: with nothing to retry it returns the
    outstanding question again.
    """
    incident, state, pipeline = _load(session, incident_id)

    if state.pending_question is not None and not health.is_awaiting_retry(incident.metrics):
        # Nothing failed; re-asking would spend a question from the budget.
        return get_state(incident_id, session)

    turn = pipeline.advance(incident, state, images=_load_images(session, state))
    _persist(session, pipeline, incident, state)
    return _to_response(incident_id, turn, state, incident)


@router.get("/{incident_id}", response_model=TurnResponse)
def get_state(
    incident_id: str, session: Session = Depends(get_session)
) -> TurnResponse:
    """Current conversation state, without advancing it.

    Used when the app reopens: it re-renders the outstanding question rather
    than restarting the conversation or asking something already answered.
    """
    incident, state, _ = _load(session, incident_id)

    if health.is_awaiting_retry(incident.metrics):
        # The last step failed and the reporter has not retried yet: show the
        # "Try again" turn rather than an empty screen.
        return _to_response(
            incident_id,
            TurnResult(
                message=SERVICE_RETRY_MESSAGE,
                awaiting_reply=True,
                action=StepAction.SERVICE_RETRY,
            ),
            state,
            incident,
        )

    if state.detection_status == "failed" and state.detections is None:
        return _to_response(
            incident_id,
            TurnResult(
                message="We could not read that photo. Please send it again "
                "from where you are standing.",
                action=StepAction.REQUEST_BETTER_PHOTO,
            ),
            state,
            incident,
        )

    pending = state.pending_question
    turn = TurnResult(
        message=pending.question if pending else None,
        options=pending.options if pending else [],
        awaiting_reply=pending is not None,
        complete=state.stage.value == "complete",
        action=(
            StepAction.ASK_WHICH_ANIMAL
            if state.pending_agent == "detection" else
            StepAction.ASK_CLARIFYING_QUESTION if pending else None
        ),
    )
    return _to_response(incident_id, turn, state, incident)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(session: Session, incident_id: str):
    """Load the incident, its conversation state, and a pipeline for it."""
    incident = repository.load_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")

    state = repository.load_conversation_state(session, incident_id)
    if state is None:
        raise HTTPException(
            status_code=409,
            detail=f"Incident {incident_id} has no active conversation.",
        )

    return incident, state, IntakePipeline(session)


def _load_images(session: Session, state) -> list[ImageInput]:
    """Re-read the incident's photos from disk for an agent call.

    The agents are stateless, so every identification or assessment pass needs
    the photos again. A missing file is skipped rather than fatal: losing a
    photo should degrade the identification, not abort an active report.
    """
    rows = session.query(PhotoRow).filter(PhotoRow.incident_id == state.incident_id).all()
    by_id = {row.photo_id: row for row in rows}

    images: list[ImageInput] = []
    for photo_id in state.photo_ids:
        row = by_id.get(photo_id)
        if row is None:
            continue
        try:
            with open(row.storage_path, "rb") as fh:
                images.append(
                    ImageInput(
                        data=fh.read(), mime_type=row.content_type or "image/jpeg",
                        photo_id=row.photo_id,
                    )
                )
        except OSError as exc:
            logger.warning("Could not read photo %s: %s", row.photo_id, exc)

    return images


def _persist(
    session: Session, pipeline: IntakePipeline, incident, state
) -> None:
    """Save the incident and conversation state, then commit.

    The route commits rather than the pipeline, so that one request is one
    transaction: if any step of `advance` raises, nothing is written.
    """
    repository.save_incident(session, incident)
    repository.save_conversation_state(session, incident.incident_id, state)
    session.commit()


def _to_response(
    incident_id: str,
    turn: TurnResult,
    state,
    incident: Incident | None = None,
) -> TurnResponse:
    """Build the client-facing payload from a pipeline turn.

    `incident` carries the environmental context and the ranked teams,
    which only exist once the reporter has shared a location -- so those
    fields are null before that and populated from then on.
    """
    assessment = state.assessment
    identification = state.identification
    return TurnResponse(
        incident_id=incident_id,
        message=turn.message,
        options=turn.options,
        awaiting_reply=turn.awaiting_reply,
        complete=turn.complete,
        action=turn.action.value if turn.action else None,
        stage=state.stage.value,
        questions_asked=state.identification_questions_asked
        + state.assessment_questions_asked,
        identified_as=identification.display_name if identification else None,
        taxon_rank=(
            identification.resolution.rank.value
            if identification and identification.resolution
            else None
        ),
        species_confidence=identification.confidence if identification else None,
        # Not gated on `turn.complete`: withholding triage until the end meant
        # the reporter learned nothing while three agents ran.
        severity_level=assessment.severity_level.value if assessment else None,
        severity_score=assessment.severity_score if assessment else None,
        severity_reasons=list(
            (incident.metrics.get("severity_reasons") or []) if incident else []
        ),
        environmental_rationale=(
            assessment.environmental_rationale if assessment else None
        ),
        injury_summary=(assessment.injury.summary or None if assessment else None),
        recommended_action=(
            assessment.recommended_action or None if assessment else None
        ),
        safety_guidance=assessment.safety_guidance or None if assessment else None,
        reporter_instructions=list(assessment.reporter_instructions) if assessment else [],
        closing_note=(
            reporter_closing_note(incident) if incident and turn.complete else None
        ),
        matched_teams=[
            ReporterTeam(
                name=candidate.name,
                distance_km=candidate.distance_km,
                eta_minutes=candidate.eta_minutes,
            )
            # Only once intake is done: mid-conversation the ranking has not
            # run, and a half-ranked list would mislead.
            for candidate in (
                incident.dispatch_candidates if incident and turn.complete else []
            )
        ],
        report_headline=None,
        conditions=build_conditions(incident.environment if incident else None),
        service_error=turn.action is StepAction.SERVICE_RETRY,
        detections=state.detections or [],
        detection_photo_id=state.detection_photo_id,
        detection_photo_url=(
            f"/incidents/{incident_id}/photos/{state.detection_photo_id}"
            if state.detection_photo_id else None
        ),
        detection_status=state.detection_status,
        selected_detection=state.selected_detection,
    )
