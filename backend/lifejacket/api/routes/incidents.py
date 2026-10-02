"""Incident endpoints: the responder console's map, detail view, and logging.

    GET   /incidents                 -> open incidents, optionally near a point
    GET   /incidents/{id}            -> full detail, including the report
    PATCH /incidents/{id}/status     -> coordinator or responder status changes
    POST  /incidents/{id}/log        -> the responder's closing write-up

The map feed returns a deliberately small payload: a phone on a coast road
should not download full reports for fifty incidents to draw fifty pins.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lifejacket.models import repository
from lifejacket.models.db import get_session
from lifejacket.models.schemas import (
    AnimalGroup,
    DispatchCandidate,
    IncidentReport,
    IncidentStatus,
)
from lifejacket.models.tables import IncidentLogRow, IncidentRow

router = APIRouter(prefix="/incidents", tags=["incidents (responder)"])


class MapPin(BaseModel):
    """One incident as it appears on the responder map."""

    incident_id: str
    latitude: float | None
    longitude: float | None
    place_name: str | None
    status: str
    severity_level: str | None
    species_common_name: str | None
    taxon_rank: str | None
    animal_group: str | None
    headline: str | None
    entanglement: bool | None
    created_at: datetime
    assigned_responder_id: str | None


class IncidentDetail(BaseModel):
    """Everything a responder needs about one incident."""

    incident_id: str
    status: str
    created_at: datetime
    updated_at: datetime

    latitude: float | None
    longitude: float | None
    place_name: str | None

    species_common_name: str | None
    species_confidence: float | None
    #: How specific the identification got: species / genus / family / group.
    taxon_rank: str | None = None
    #: Per-species probabilities inside the resolved taxon. For an "Oceanic
    #: dolphins" answer this lists common 0.48 and bottlenose 0.41.
    species_candidates: list[dict] = Field(default_factory=list)
    animal_group: str | None

    severity_level: str | None
    severity_score: float | None
    severity_reasons: list[str] = Field(default_factory=list)

    report: IncidentReport | None = None
    dispatch_candidates: list[DispatchCandidate] = Field(default_factory=list)

    #: Transcript, so a responder can read exactly what the reporter said
    #: rather than only the agent's summary of it.
    transcript: list[dict] = Field(default_factory=list)
    environment: dict | None = None

    reporter_phone: str | None = None
    duplicate_of: str | None = None
    assigned_responder_id: str | None = None

    #: True when the guardrail check failed or triage confidence was low, so
    #: the console can mark it as needing a coordinator's eyes.
    requires_human_review: bool = False
    guardrail: dict | None = None


class StatusUpdate(BaseModel):
    status: IncidentStatus
    responder_id: str | None = None


class LogRequest(BaseModel):
    """A responder's closing notes.

    `confirmed_species` is the most valuable field in the whole system: it is
    the only ground truth we ever get about whether the identification agent
    was right.
    """

    responder_id: str
    confirmed_species: str | None = None
    confirmed_animal_group: AnimalGroup | None = None
    outcome: str | None = Field(
        default=None,
        description="rescued, released, deceased, not_found, no_action_needed",
    )
    actions_taken: str | None = None
    notes: str | None = None
    report_was_accurate: bool | None = None
    arrival_time: datetime | None = None
    departure_time: datetime | None = None


@router.get("", response_model=list[MapPin])
def list_incidents(
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float = Query(default=50.0, gt=0, le=500),
    session: Session = Depends(get_session),
) -> list[MapPin]:
    """Open incidents, newest first, optionally within a radius.

    Supply `latitude` and `longitude` to get only nearby incidents; omit them
    and a coordinator sees everything still open.
    """
    rows = repository.find_open_incidents(session, latitude, longitude, radius_km)

    return [
        MapPin(
            incident_id=row.incident_id,
            latitude=row.latitude,
            longitude=row.longitude,
            place_name=row.place_name,
            status=row.status,
            severity_level=row.severity_level,
            species_common_name=row.species_common_name,
            taxon_rank=row.taxon_rank,
            animal_group=row.animal_group,
            headline=row.report_headline,
            entanglement=row.entanglement_present,
            created_at=row.created_at,
            assigned_responder_id=row.assigned_responder_id,
        )
        for row in rows
    ]


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(
    incident_id: str, session: Session = Depends(get_session)
) -> IncidentDetail:
    """Full detail for one incident."""
    row = session.get(IncidentRow, incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")

    metrics = row.metrics_json or {}
    guardrail = metrics.get("guardrail")
    assessment = row.assessment_json or {}

    # Held for review if the guardrail found problems, or if the assessment
    # itself asked for human eyes.
    requires_review = bool(assessment.get("requires_human_review"))
    if guardrail and not (guardrail.get("is_grounded") and guardrail.get("is_safe")):
        requires_review = True

    return IncidentDetail(
        incident_id=row.incident_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        latitude=row.latitude,
        longitude=row.longitude,
        place_name=row.place_name,
        species_common_name=row.species_common_name,
        species_confidence=row.species_confidence,
        taxon_rank=row.taxon_rank,
        species_candidates=_species_breakdown(row.identification_json),
        animal_group=row.animal_group,
        severity_level=row.severity_level,
        severity_score=row.severity_score,
        severity_reasons=metrics.get("severity_reasons", []),
        report=(
            IncidentReport.model_validate(row.report_json) if row.report_json else None
        ),
        dispatch_candidates=[
            DispatchCandidate.model_validate(c)
            for c in (row.dispatch_candidates_json or [])
        ],
        transcript=[
            {
                "role": m.role,
                "content": m.content,
                "agent_name": m.agent_name,
                "created_at": m.created_at.isoformat(),
            }
            for m in row.messages
        ],
        environment=row.environment_json,
        reporter_phone=row.reporter_phone,
        duplicate_of=row.duplicate_of,
        assigned_responder_id=row.assigned_responder_id,
        requires_human_review=requires_review,
        guardrail=guardrail,
    )


@router.patch("/{incident_id}/status", response_model=dict)
def update_status(
    incident_id: str, body: StatusUpdate, session: Session = Depends(get_session)
) -> dict:
    """Move an incident through its lifecycle.

    Used by the console for coordinator decisions (dispatch, cancel) and by the
    responder app for field updates (en route, on scene).
    """
    row = session.get(IncidentRow, incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")

    row.status = body.status.value
    row.updated_at = datetime.now()
    if body.responder_id:
        row.assigned_responder_id = body.responder_id

    session.commit()
    return {"incident_id": incident_id, "status": row.status}


@router.post("/{incident_id}/log", response_model=dict)
def log_incident(
    incident_id: str, body: LogRequest, session: Session = Depends(get_session)
) -> dict:
    """Record a responder's closing notes and resolve the incident.

    Resolving here rather than in a separate call means an incident cannot be
    closed without a log entry -- which is what keeps the ground-truth dataset
    complete enough to evaluate the agents against.
    """
    row = session.get(IncidentRow, incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")

    session.add(
        IncidentLogRow(
            incident_id=incident_id,
            responder_id=body.responder_id,
            confirmed_species=body.confirmed_species,
            confirmed_animal_group=(
                body.confirmed_animal_group.value if body.confirmed_animal_group else None
            ),
            outcome=body.outcome,
            actions_taken=body.actions_taken,
            notes=body.notes,
            report_was_accurate=body.report_was_accurate,
            arrival_time=body.arrival_time,
            departure_time=body.departure_time,
        )
    )

    row.status = IncidentStatus.RESOLVED.value
    row.updated_at = datetime.now()
    session.commit()

    return {"incident_id": incident_id, "status": row.status, "logged": True}


def _species_breakdown(identification_json: dict | None) -> list[dict]:
    """Species probabilities for the console, most likely first.

    Uses the resolved taxon's members when present -- those are the species
    the answer covers -- and otherwise every candidate the agent considered.
    """
    if not identification_json:
        return []
    resolution = identification_json.get("resolution") or {}
    species = resolution.get("members") or identification_json.get("candidates") or []
    return [
        {
            "common_name": s.get("common_name"),
            "scientific_name": s.get("scientific_name"),
            "confidence": s.get("confidence"),
        }
        for s in sorted(species, key=lambda s: s.get("confidence") or 0, reverse=True)
    ]
