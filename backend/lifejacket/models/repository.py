"""Reading and writing incidents: the boundary between Pydantic and SQLAlchemy.

All conversion between the domain models (`schemas.py`) and the database rows
(`tables.py`) happens here. Keeping it in one module means the promoted-column
duplication described in `tables.py` is maintained in exactly one place --
everywhere else works with `Incident` objects and never sees the split.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifejacket.chatbot.session import ConversationState
from lifejacket.dispatch.duplicates import CandidateIncident
from lifejacket.geo import bounding_box, haversine_km
from lifejacket.models.schemas import (
    AnimalGroup,
    AssessmentResult,
    ChatMessage,
    ChatRole,
    ClarifyingQuestion,
    ConversationStage,
    EnvironmentalContext,
    GeoPoint,
    IdentificationResult,
    Incident,
    IncidentReport,
    IncidentStatus,
)
from lifejacket.models.tables import ChatMessageRow, IncidentRow, PhotoRow


def new_incident_id() -> str:
    """A short, readable, collision-resistant incident ID.

    Eight hex characters gives about 4 billion values -- ample for a project of
    this size, and short enough to read aloud over a radio, which matters when
    a coordinator is relaying it to a responder in the field.
    """
    return f"INC_{uuid.uuid4().hex[:8]}"


def new_photo_id() -> str:
    return f"PHOTO_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def save_incident(session: Session, incident: Incident) -> IncidentRow:
    """Insert or update an incident. Returns the persisted row.

    Promoted columns are recomputed from the nested objects on every save, so
    they cannot drift out of sync with the JSON they are derived from.
    """
    row = session.get(IncidentRow, incident.incident_id)
    if row is None:
        row = IncidentRow(incident_id=incident.incident_id)
        session.add(row)

    row.status = incident.status.value
    row.updated_at = datetime.now()
    row.reporter_id = incident.reporter_id
    row.reporter_phone = incident.reporter_phone

    if incident.location:
        row.latitude = incident.location.latitude
        row.longitude = incident.location.longitude
        row.place_name = incident.location.place_name
        row.location_source = incident.location.source

    # --- Promoted from identification ---
    if incident.identification:
        # The *resolved* taxon, which may be a genus or family ("Oceanic
        # dolphins") rather than a species. Per-species probabilities stay in
        # identification_json under resolution.members.
        identification = incident.identification
        row.species_common_name = identification.display_name
        row.species_confidence = identification.confidence
        row.animal_group = identification.animal_group.value
        row.taxon_rank = (
            identification.resolution.rank.value if identification.resolution else None
        )
        row.identification_json = identification.model_dump(mode="json")

    # --- Promoted from assessment ---
    if incident.assessment:
        row.severity_level = incident.assessment.severity_level.value
        row.severity_score = incident.assessment.severity_score
        row.injury_present = incident.assessment.injury.injury_present
        row.entanglement_present = incident.assessment.injury.entanglement
        row.assessment_json = incident.assessment.model_dump(mode="json")

    if incident.report:
        row.report_headline = incident.report.headline
        row.report_json = incident.report.model_dump(mode="json")

    if incident.environment:
        row.environment_json = incident.environment.model_dump(mode="json")

    row.dispatch_candidates_json = [
        c.model_dump(mode="json") for c in incident.dispatch_candidates
    ]
    row.metrics_json = incident.metrics
    row.assigned_responder_id = incident.assigned_responder_id
    row.duplicate_of = incident.duplicate_of

    session.flush()
    return row


def save_photo(
    session: Session,
    incident_id: str,
    storage_path: str,
    content_type: str | None = None,
    exif_latitude: float | None = None,
    exif_longitude: float | None = None,
    exif_captured_at: datetime | None = None,
) -> PhotoRow:
    """Record an uploaded photo. The bytes live on disk, not in the row."""
    row = PhotoRow(
        photo_id=new_photo_id(),
        incident_id=incident_id,
        storage_path=storage_path,
        content_type=content_type,
        exif_latitude=exif_latitude,
        exif_longitude=exif_longitude,
        exif_captured_at=exif_captured_at,
    )
    session.add(row)
    session.flush()
    return row


def save_messages(
    session: Session, incident_id: str, messages: list[ChatMessage]
) -> None:
    """Replace the stored transcript for an incident.

    Replace rather than append because the caller holds the full transcript in
    the conversation state, and reconciling two partial views of the same list
    is a bug waiting to happen. Transcripts are short, so the rewrite is cheap.
    """
    session.query(ChatMessageRow).filter(
        ChatMessageRow.incident_id == incident_id
    ).delete()

    for message in messages:
        session.add(
            ChatMessageRow(
                incident_id=incident_id,
                role=message.role.value,
                content=message.content,
                created_at=message.created_at,
                agent_name=message.agent_name,
                feature=message.feature,
                options_json=message.options or None,
            )
        )
    session.flush()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def save_conversation_state(
    session: Session, incident_id: str, state: ConversationState
) -> None:
    """Persist the chatbot state so the next request can resume the conversation."""
    row = session.get(IncidentRow, incident_id)
    if row is None:
        raise KeyError(f"Unknown incident: {incident_id}")
    row.conversation_state_json = _state_to_json(state)
    session.flush()


def load_conversation_state(
    session: Session, incident_id: str
) -> ConversationState | None:
    """Rebuild the chatbot state, or None if this incident has none stored."""
    row = session.get(IncidentRow, incident_id)
    if row is None or not row.conversation_state_json:
        return None
    return _state_from_json(row.conversation_state_json)


def _state_to_json(state: ConversationState) -> dict:
    """Serialise `ConversationState`.

    Hand-written rather than using `dataclasses.asdict` because the state holds
    Pydantic models and enums, which `asdict` turns into objects JSON cannot
    encode.
    """
    return {
        "incident_id": state.incident_id,
        "stage": state.stage.value,
        "photo_ids": state.photo_ids,
        "has_location": state.has_location,
        "transcript": [m.model_dump(mode="json") for m in state.transcript],
        "identification": (
            state.identification.model_dump(mode="json") if state.identification else None
        ),
        "assessment": (
            state.assessment.model_dump(mode="json") if state.assessment else None
        ),
        "identification_questions_asked": state.identification_questions_asked,
        "assessment_questions_asked": state.assessment_questions_asked,
        "better_photo_requested": state.better_photo_requested,
        "probed_features": state.probed_features,
        "identification_stop_reason": state.identification_stop_reason,
        "pending_agent": state.pending_agent,
        "identification_stale": state.identification_stale,
        "assessment_stale": state.assessment_stale,
        "pending_question": (
            state.pending_question.model_dump(mode="json")
            if state.pending_question
            else None
        ),
    }


def _state_from_json(data: dict) -> ConversationState:
    """Inverse of `_state_to_json`."""
    return ConversationState(
        incident_id=data["incident_id"],
        stage=ConversationStage(data.get("stage", ConversationStage.AWAITING_PHOTO.value)),
        photo_ids=data.get("photo_ids", []),
        has_location=data.get("has_location", False),
        transcript=[ChatMessage.model_validate(m) for m in data.get("transcript", [])],
        identification=(
            IdentificationResult.model_validate(data["identification"])
            if data.get("identification")
            else None
        ),
        assessment=(
            AssessmentResult.model_validate(data["assessment"])
            if data.get("assessment")
            else None
        ),
        identification_questions_asked=data.get("identification_questions_asked", 0),
        assessment_questions_asked=data.get("assessment_questions_asked", 0),
        better_photo_requested=data.get("better_photo_requested", False),
        probed_features=data.get("probed_features", []),
        identification_stop_reason=data.get("identification_stop_reason"),
        pending_agent=data.get("pending_agent"),
        identification_stale=data.get("identification_stale", False),
        assessment_stale=data.get("assessment_stale", False),
        pending_question=(
            ClarifyingQuestion.model_validate(data["pending_question"])
            if data.get("pending_question")
            else None
        ),
    )


def load_incident(session: Session, incident_id: str) -> Incident | None:
    """Rebuild a full `Incident` from its row, or None if not found."""
    row = session.get(IncidentRow, incident_id)
    return row_to_incident(row) if row else None


def row_to_incident(row: IncidentRow) -> Incident:
    """Convert a row back into the domain model.

    Reads from the JSON columns, not the promoted ones -- the JSON is the
    source of truth and the columns are a query-time convenience.
    """
    location = None
    if row.latitude is not None and row.longitude is not None:
        location = GeoPoint(
            latitude=row.latitude,
            longitude=row.longitude,
            place_name=row.place_name,
            source=row.location_source or "device_gps",
        )

    return Incident(
        incident_id=row.incident_id,
        status=IncidentStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        reporter_id=row.reporter_id,
        reporter_phone=row.reporter_phone,
        location=location,
        photo_ids=[p.photo_id for p in row.photos],
        identification=(
            IdentificationResult.model_validate(row.identification_json)
            if row.identification_json
            else None
        ),
        assessment=(
            AssessmentResult.model_validate(row.assessment_json)
            if row.assessment_json
            else None
        ),
        report=(
            IncidentReport.model_validate(row.report_json) if row.report_json else None
        ),
        environment=(
            EnvironmentalContext.model_validate(row.environment_json)
            if row.environment_json
            else None
        ),
        assigned_responder_id=row.assigned_responder_id,
        duplicate_of=row.duplicate_of,
        metrics=row.metrics_json or {},
    )


def load_transcript(session: Session, incident_id: str) -> list[ChatMessage]:
    """The conversation for an incident, in order."""
    rows = session.scalars(
        select(ChatMessageRow)
        .where(ChatMessageRow.incident_id == incident_id)
        .order_by(ChatMessageRow.id)
    ).all()

    return [
        ChatMessage(
            role=ChatRole(row.role),
            content=row.content,
            created_at=row.created_at,
            agent_name=row.agent_name,
            feature=row.feature,
            options=row.options_json or [],
        )
        for row in rows
    ]


def find_open_incidents(
    session: Session,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 50.0,
) -> list[IncidentRow]:
    """Incidents still needing attention, for the responder map.

    Optionally restricted to a radius, which is how the responder app shows
    "incidents near me" without downloading the whole table.
    """
    closed = {
        IncidentStatus.RESOLVED.value,
        IncidentStatus.CANCELLED.value,
        IncidentStatus.GUIDANCE_ONLY.value,
    }
    statement = select(IncidentRow).where(IncidentRow.status.not_in(closed))

    if latitude is not None and longitude is not None:
        # Cheap rectangular pre-filter in SQL, then exact distance in Python.
        # Avoids computing haversine over every row in the table.
        min_lat, max_lat, min_lon, max_lon = bounding_box(latitude, longitude, radius_km)
        statement = statement.where(
            IncidentRow.latitude.between(min_lat, max_lat),
            IncidentRow.longitude.between(min_lon, max_lon),
        )

    rows = list(session.scalars(statement.order_by(IncidentRow.created_at.desc())).all())

    if latitude is not None and longitude is not None:
        rows = [
            row
            for row in rows
            if row.latitude is not None
            and row.longitude is not None
            and haversine_km(latitude, longitude, row.latitude, row.longitude) <= radius_km
        ]

    return rows


def find_duplicate_candidates(
    session: Session,
    incident_id: str,
    latitude: float,
    longitude: float,
    within_hours: float = 24.0,
    within_km: float = 2.0,
) -> list[CandidateIncident]:
    """Recent nearby incidents to check a new report against.

    The windows here are slightly wider than the duplicate scorer's own
    thresholds, so that borderline cases are still scored rather than excluded
    by the query before `duplicates.find_duplicate` ever sees them.
    """
    since = datetime.now() - timedelta(hours=within_hours)
    min_lat, max_lat, min_lon, max_lon = bounding_box(latitude, longitude, within_km)

    rows = session.scalars(
        select(IncidentRow).where(
            IncidentRow.incident_id != incident_id,
            IncidentRow.created_at >= since,
            IncidentRow.latitude.between(min_lat, max_lat),
            IncidentRow.longitude.between(min_lon, max_lon),
            # A report already judged a duplicate is not itself a match target;
            # otherwise duplicates chain into long speculative clusters.
            IncidentRow.duplicate_of.is_(None),
        )
    ).all()

    return [
        CandidateIncident(
            incident_id=row.incident_id,
            latitude=row.latitude,
            longitude=row.longitude,
            reported_at=row.created_at,
            animal_group=(
                AnimalGroup(row.animal_group) if row.animal_group else AnimalGroup.UNKNOWN
            ),
            species_common_name=row.species_common_name,
        )
        for row in rows
    ]
