"""Reporter-facing endpoints: the intake conversation.

The flow a phone client follows:

    POST /intake/start                 -> incident_id, first prompt
    POST /intake/{id}/photo            -> upload a photo (repeatable)
    POST /intake/{id}/location         -> share GPS; triggers tide/weather
    POST /intake/{id}/reply            -> answer a question; returns the next one
    GET  /intake/{id}                  -> current state, for resuming

Every mutating endpoint returns the same `TurnResponse` shape, so the client
has one rendering path regardless of which call produced the turn.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lifejacket.config import settings
from lifejacket.llm.client import ImageInput
from lifejacket.models import repository
from lifejacket.models.db import get_session
from lifejacket.models.schemas import GeoPoint
from lifejacket.models.tables import PhotoRow
from lifejacket.services.pipeline import IntakePipeline, TurnResult

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
    #: Present once intake finishes, so the app can show the outcome.
    severity_level: str | None = None
    report_headline: str | None = None


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
    return _to_response(incident.incident_id, turn, state)


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

    pipeline.attach_photo(state, photo_row.photo_id)

    turn = pipeline.advance(
        incident, state, images=[ImageInput(data=data, mime_type=file.content_type)]
    )
    _persist(session, pipeline, incident, state)
    return _to_response(incident_id, turn, state)


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

    turn = pipeline.advance(incident, state, images=_load_images(session, incident_id))
    _persist(session, pipeline, incident, state)
    return _to_response(incident_id, turn, state)


@router.post("/{incident_id}/reply", response_model=TurnResponse)
def submit_reply(
    incident_id: str, body: ReplyRequest, session: Session = Depends(get_session)
) -> TurnResponse:
    """Answer the outstanding question and get the next turn."""
    incident, state, pipeline = _load(session, incident_id)

    # Any text is accepted: options are shortcuts for tapping, not a whitelist.
    # The agent reads the reply in context, so "the left one, I think" is fine.
    pipeline.submit_reply(state, body.text)

    turn = pipeline.advance(incident, state, images=_load_images(session, incident_id))
    _persist(session, pipeline, incident, state)
    return _to_response(incident_id, turn, state)


@router.get("/{incident_id}", response_model=TurnResponse)
def get_state(
    incident_id: str, session: Session = Depends(get_session)
) -> TurnResponse:
    """Current conversation state, without advancing it.

    Used when the app reopens: it re-renders the outstanding question rather
    than restarting the conversation or asking something already answered.
    """
    incident, state, _ = _load(session, incident_id)

    pending = state.pending_question
    turn = TurnResult(
        message=pending.question if pending else None,
        options=pending.options if pending else [],
        awaiting_reply=pending is not None,
        complete=state.stage.value == "complete",
    )
    return _to_response(incident_id, turn, state)


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


def _load_images(session: Session, incident_id: str) -> list[ImageInput]:
    """Re-read the incident's photos from disk for an agent call.

    The agents are stateless, so every identification or assessment pass needs
    the photos again. A missing file is skipped rather than fatal: losing a
    photo should degrade the identification, not abort an active report.
    """
    rows = session.query(PhotoRow).filter(PhotoRow.incident_id == incident_id).all()

    images: list[ImageInput] = []
    for row in rows:
        try:
            with open(row.storage_path, "rb") as fh:
                images.append(
                    ImageInput(
                        data=fh.read(), mime_type=row.content_type or "image/jpeg"
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


def _to_response(incident_id: str, turn: TurnResult, state) -> TurnResponse:
    """Build the client-facing payload from a pipeline turn."""
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
        severity_level=(
            assessment.severity_level.value if assessment and turn.complete else None
        ),
        report_headline=None,
    )
