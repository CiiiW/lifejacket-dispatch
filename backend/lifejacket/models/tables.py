"""SQLAlchemy tables -- how incidents are actually stored.

Design note, because the shape here is a deliberate compromise:

The agents produce deeply nested objects (`AssessmentResult` contains an
`InjuryAssessment` contains ten booleans). Modelling every leaf as a column
would mean a migration every time a prompt changes, which during a research
project is weekly. Modelling everything as one JSON blob would make the
responder map impossible to query.

So we do both. Fields that the application **filters, sorts, or maps on** are
real columns. Everything else is kept in a JSON column alongside, as the full
fidelity record. The rule of thumb: if a SQL `WHERE` clause needs it, promote
it; otherwise leave it in JSON.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Base class for all tables. `Base.metadata` drives table creation."""

    # JSON works on both SQLite and Postgres, so the type map stays portable.
    type_annotation_map = {dict: JSON, list: JSON}


class IncidentRow(Base):
    """One reported animal. The central table of the system."""

    __tablename__ = "incidents"

    incident_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    reporter_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reporter_phone: Mapped[str | None] = mapped_column(String(32))

    # --- Promoted: the responder map queries by location constantly ---
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    place_name: Mapped[str | None] = mapped_column(String(256))
    location_source: Mapped[str | None] = mapped_column(String(32))

    # --- Promoted: triage lists sort by severity and filter by group ---
    species_common_name: Mapped[str | None] = mapped_column(String(128), index=True)
    species_confidence: Mapped[float | None] = mapped_column(Float)
    # species / genus / family / group: how specific the identification got.
    # "species_common_name" holds the label at that rank, e.g. "Oceanic dolphins".
    taxon_rank: Mapped[str | None] = mapped_column(String(16))
    animal_group: Mapped[str | None] = mapped_column(String(32), index=True)
    severity_level: Mapped[str | None] = mapped_column(String(16), index=True)
    severity_score: Mapped[float | None] = mapped_column(Float)
    injury_present: Mapped[bool | None] = mapped_column(Boolean, index=True)
    entanglement_present: Mapped[bool | None] = mapped_column(Boolean, index=True)

    # --- Promoted: the notification card is read far more often than opened ---
    report_headline: Mapped[str | None] = mapped_column(String(256))

    # --- Full-fidelity agent output, validated back into Pydantic on read ---
    identification_json: Mapped[dict | None] = mapped_column(JSON)
    assessment_json: Mapped[dict | None] = mapped_column(JSON)
    report_json: Mapped[dict | None] = mapped_column(JSON)
    environment_json: Mapped[dict | None] = mapped_column(JSON)
    dispatch_candidates_json: Mapped[list | None] = mapped_column(JSON)
    metrics_json: Mapped[dict | None] = mapped_column(JSON)

    # The chatbot's resumable state (stage, question counts, probed features).
    # Persisted because each reporter reply is a separate HTTP request and the
    # conversation must survive the app being closed mid-intake.
    conversation_state_json: Mapped[dict | None] = mapped_column(JSON)

    assigned_responder_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("responders.responder_id")
    )
    # Self-reference: set when this report is judged to be the same animal as
    # an earlier one. We keep the duplicate rather than deleting it, because two
    # independent reports are useful evidence that something is really there.
    duplicate_of: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("incidents.incident_id")
    )

    photos: Mapped[list[PhotoRow]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    messages: Mapped[list[ChatMessageRow]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="ChatMessageRow.id",
    )
    assignments: Mapped[list[AssignmentRow]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    logs: Mapped[list[IncidentLogRow]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )


class PhotoRow(Base):
    """A photo submitted by the reporter.

    Only the path and metadata live in the database. The image bytes stay on
    disk (or in a bucket) because photos of a stranding location can be
    personally identifying and should be deletable independently of the record.
    """

    __tablename__ = "photos"

    photo_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("incidents.incident_id"), index=True
    )
    storage_path: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str | None] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # EXIF often carries a more accurate location than a hand-typed one, and a
    # capture timestamp that tells us how stale the sighting is.
    exif_latitude: Mapped[float | None] = mapped_column(Float)
    exif_longitude: Mapped[float | None] = mapped_column(Float)
    exif_captured_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Set by the identification agent so we can ask for a retake once, not twice.
    quality_note: Mapped[str | None] = mapped_column(Text)

    incident: Mapped[IncidentRow] = relationship(back_populates="photos")


class ChatMessageRow(Base):
    """One turn of the reporter conversation.

    Stored in full because the transcript is the project's richest research
    asset: it shows which questions actually resolved ambiguity.
    """

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("incidents.incident_id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    agent_name: Mapped[str | None] = mapped_column(String(32))
    feature: Mapped[str | None] = mapped_column(String(64))
    options_json: Mapped[list | None] = mapped_column(JSON)

    incident: Mapped[IncidentRow] = relationship(back_populates="messages")


class ResponderRow(Base):
    """A rescue organisation or trained volunteer who can be dispatched."""

    __tablename__ = "responders"

    responder_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(16), index=True)  # organisation | volunteer

    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(256))
    hotline: Mapped[str | None] = mapped_column(String(64))
    website: Mapped[str | None] = mapped_column(String(256))

    # Base location, used for distance scoring when no live position is known.
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # Free text straight from the stranding-network directory. Matched by term
    # overlap rather than parsed, because the formats are wildly inconsistent.
    response_area: Mapped[str | None] = mapped_column(Text)
    response_type: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(256))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Volunteers toggle this when they are available to take a call.
    is_on_duty: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Last known live position, for the reporter's "who is coming" map.
    last_latitude: Mapped[float | None] = mapped_column(Float)
    last_longitude: Mapped[float | None] = mapped_column(Float)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)

    assignments: Mapped[list[AssignmentRow]] = relationship(back_populates="responder")


class AssignmentRow(Base):
    """A responder being offered, or taking on, an incident.

    Separate from `incidents.assigned_responder_id` because an incident can be
    offered to several responders before one accepts, and we want that history.
    """

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("incidents.incident_id"), index=True
    )
    responder_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("responders.responder_id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    offered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Snapshot of the score at offer time. Kept even if weights later change,
    # so we can audit why this responder was chosen on this day.
    match_score: Mapped[float | None] = mapped_column(Float)
    match_rationale: Mapped[str | None] = mapped_column(Text)
    distance_km: Mapped[float | None] = mapped_column(Float)
    eta_minutes: Mapped[float | None] = mapped_column(Float)

    incident: Mapped[IncidentRow] = relationship(back_populates="assignments")
    responder: Mapped[ResponderRow] = relationship(back_populates="assignments")


class IncidentLogRow(Base):
    """The responder's closing write-up.

    `confirmed_species` is ground truth. It is the only column in the schema
    that lets us measure whether the identification agent is actually right.
    """

    __tablename__ = "incident_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("incidents.incident_id"), index=True
    )
    responder_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    confirmed_species: Mapped[str | None] = mapped_column(String(128))
    confirmed_animal_group: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str | None] = mapped_column(String(32), index=True)
    actions_taken: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    report_was_accurate: Mapped[bool | None] = mapped_column(Boolean)
    arrival_time: Mapped[datetime | None] = mapped_column(DateTime)
    departure_time: Mapped[datetime | None] = mapped_column(DateTime)

    incident: Mapped[IncidentRow] = relationship(back_populates="logs")
