"""Responder endpoints: who is available, where they are, and who is going.

    GET  /responders                       -> the directory
    POST /responders/seed                  -> load rescue_centers.csv into the DB
    POST /responders/geocode               -> approximate coordinates for the map
    POST /responders/{id}/location         -> live position for the reporter's map
    POST /responders/{id}/duty             -> volunteer availability toggle
    POST /responders/assign                -> coordinator approves a dispatch
    POST /responders/assignments/{id}/respond -> responder accepts or declines

The coordinator approval step in `/assign` is not optional ceremony. Stranding
networks operate under permits, and an automated dispatch would place an
untrained person next to a protected animal with no human having agreed to it.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifejacket.context.geocode import forward_geocode, service_area_queries
from lifejacket.dispatch.matching import center_id, load_rescue_centers
from lifejacket.geo import estimate_drive_minutes, haversine_km
from lifejacket.models.db import get_session
from lifejacket.models.schemas import AssignmentStatus, ResponderKind
from lifejacket.models.tables import AssignmentRow, IncidentRow, ResponderRow

router = APIRouter(prefix="/responders", tags=["responders"])


class ResponderOut(BaseModel):
    responder_id: str
    name: str
    kind: str
    phone: str | None = None
    hotline: str | None = None
    email: str | None = None
    response_area: str | None = None
    response_type: str | None = None
    is_on_duty: bool = False
    #: Where the centre is based. Needed to plot it on the console's map, and
    #: distinct from `last_latitude` below, which is where a responder
    #: currently *is* after checking in from the field.
    latitude: float | None = None
    longitude: float | None = None
    last_latitude: float | None = None
    last_longitude: float | None = None
    last_seen_at: datetime | None = None


class LocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class DutyUpdate(BaseModel):
    is_on_duty: bool


class AssignRequest(BaseModel):
    incident_id: str
    responder_id: str
    #: Who approved this. Recorded because a permitted dispatch needs a name
    #: against it, not just a timestamp.
    approved_by: str
    match_score: float | None = None
    match_rationale: str | None = None


class RespondRequest(BaseModel):
    accept: bool
    note: str | None = None


class EtaResponse(BaseModel):
    """What the reporter's map shows about an incoming responder."""

    responder_id: str
    name: str
    latitude: float | None
    longitude: float | None
    distance_km: float | None
    eta_minutes: float | None
    status: str


@router.get("", response_model=list[ResponderOut])
def list_responders(
    on_duty_only: bool = False, session: Session = Depends(get_session)
) -> list[ResponderOut]:
    """The responder directory."""
    statement = select(ResponderRow).where(ResponderRow.is_active.is_(True))
    if on_duty_only:
        statement = statement.where(ResponderRow.is_on_duty.is_(True))

    return [
        ResponderOut(
            responder_id=row.responder_id,
            name=row.name,
            kind=row.kind,
            phone=row.phone,
            hotline=row.hotline,
            email=row.email,
            response_area=row.response_area,
            response_type=row.response_type,
            is_on_duty=row.is_on_duty,
            latitude=row.latitude,
            longitude=row.longitude,
            last_latitude=row.last_latitude,
            last_longitude=row.last_longitude,
            last_seen_at=row.last_seen_at,
        )
        for row in session.scalars(statement).all()
    ]


@router.post("/geocode", response_model=dict)
def geocode_responders(
    overwrite: bool = False, session: Session = Depends(get_session)
) -> dict:
    """Give rescue centres approximate coordinates so the map can plot them.

    The 2026 stranding directory lists coverage as prose ("Del Norte and
    Humboldt Counties, California") and no street address, so there is nothing
    exact to geocode. This resolves the *service area* instead, which puts a
    centre somewhere inside the region it covers.

    That is good enough to see which part of the coast is served and to draw a
    rough route, and not good enough to drive to. Replace it with real
    addresses before anyone relies on these pins.

    Nominatim's usage policy allows one request a second, so the full
    directory takes a couple of minutes. Idempotent: centres that already have
    coordinates are skipped unless `overwrite` is set.
    """
    statement = select(ResponderRow).where(ResponderRow.is_active.is_(True))
    located = skipped = failed = 0
    unresolved: list[str] = []

    for row in session.scalars(statement).all():
        if row.latitude is not None and row.longitude is not None and not overwrite:
            skipped += 1
            continue

        coordinates = None
        for query in service_area_queries(row.response_area, row.name):
            coordinates = forward_geocode(query)
            if coordinates is not None:
                break

        if coordinates is None:
            failed += 1
            unresolved.append(row.name)
            continue

        row.latitude, row.longitude = coordinates
        located += 1

    session.commit()
    return {
        "located": located,
        "skipped": skipped,
        "failed": failed,
        "unresolved": unresolved,
        "precision": "service_area_centroid",
    }


@router.post("/seed", response_model=dict)
def seed_responders(session: Session = Depends(get_session)) -> dict:
    """Load `data/rescue_centers.csv` into the responders table.

    Idempotent: existing organisations are updated rather than duplicated,
    since IDs are derived from the organisation name. Safe to re-run after the
    annual directory update.
    """
    created = updated = 0

    for center in load_rescue_centers():
        responder_id = center_id(center.center_name)
        row = session.get(ResponderRow, responder_id)

        if row is None:
            row = ResponderRow(
                responder_id=responder_id, kind=ResponderKind.ORGANISATION.value
            )
            session.add(row)
            created += 1
        else:
            updated += 1

        row.name = center.center_name
        row.phone = center.phone
        row.hotline = center.hotline
        row.email = center.email
        row.website = center.website
        row.response_area = center.response_area
        row.response_type = center.response_type
        row.source = center.source
        row.latitude = center.latitude
        row.longitude = center.longitude
        row.is_active = True

    session.commit()
    return {"created": created, "updated": updated}


@router.post("/{responder_id}/location", response_model=dict)
def update_location(
    responder_id: str, body: LocationUpdate, session: Session = Depends(get_session)
) -> dict:
    """Report a responder's live position.

    Called periodically by the responder app while it has an active
    assignment. This is what lets the reporter see help approaching, which is
    the single most reassuring thing the app can show someone standing with a
    dying animal.
    """
    row = session.get(ResponderRow, responder_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown responder: {responder_id}")

    row.last_latitude = body.latitude
    row.last_longitude = body.longitude
    row.last_seen_at = datetime.now()
    session.commit()

    return {"responder_id": responder_id, "updated_at": row.last_seen_at.isoformat()}


@router.post("/{responder_id}/duty", response_model=dict)
def set_duty(
    responder_id: str, body: DutyUpdate, session: Session = Depends(get_session)
) -> dict:
    """Toggle a volunteer's availability."""
    row = session.get(ResponderRow, responder_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown responder: {responder_id}")

    row.is_on_duty = body.is_on_duty
    session.commit()
    return {"responder_id": responder_id, "is_on_duty": row.is_on_duty}


@router.post("/assign", response_model=dict)
def assign_responder(
    body: AssignRequest, session: Session = Depends(get_session)
) -> dict:
    """A coordinator approves offering an incident to a responder.

    Creates an `OFFERED` assignment. The responder then accepts or declines --
    an offer is not an assumption that they are going.
    """
    incident = session.get(IncidentRow, body.incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {body.incident_id}")

    responder = session.get(ResponderRow, body.responder_id)
    if responder is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown responder: {body.responder_id}"
        )

    distance_km = eta_minutes = None
    incident_located = None not in (incident.latitude, incident.longitude)
    responder_located = None not in (responder.latitude, responder.longitude)
    if incident_located and responder_located:
        distance_km = round(
            haversine_km(
                incident.latitude, incident.longitude, responder.latitude, responder.longitude
            ),
            1,
        )
        eta_minutes = round(estimate_drive_minutes(distance_km))

    assignment = AssignmentRow(
        incident_id=body.incident_id,
        responder_id=body.responder_id,
        status=AssignmentStatus.OFFERED.value,
        match_score=body.match_score,
        match_rationale=(
            f"Approved by {body.approved_by}. {body.match_rationale or ''}".strip()
        ),
        distance_km=distance_km,
        eta_minutes=eta_minutes,
    )
    session.add(assignment)

    incident.status = "dispatched"
    incident.updated_at = datetime.now()
    session.commit()

    return {
        "assignment_id": assignment.id,
        "incident_id": body.incident_id,
        "responder_id": body.responder_id,
        "status": assignment.status,
        "eta_minutes": eta_minutes,
    }


@router.post("/assignments/{assignment_id}/respond", response_model=dict)
def respond_to_assignment(
    assignment_id: int, body: RespondRequest, session: Session = Depends(get_session)
) -> dict:
    """A responder accepts or declines an offered incident.

    On a decline the incident returns to `awaiting_dispatch` so the coordinator
    can offer it to the next candidate. It must not silently stay "dispatched"
    with nobody actually going.
    """
    assignment = session.get(AssignmentRow, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail=f"Unknown assignment: {assignment_id}")

    assignment.status = (
        AssignmentStatus.ACCEPTED.value if body.accept else AssignmentStatus.DECLINED.value
    )
    assignment.responded_at = datetime.now()

    incident = session.get(IncidentRow, assignment.incident_id)
    if incident is not None:
        if body.accept:
            incident.status = "accepted"
            incident.assigned_responder_id = assignment.responder_id
        else:
            incident.status = "awaiting_dispatch"
            incident.assigned_responder_id = None
        incident.updated_at = datetime.now()

    session.commit()
    return {"assignment_id": assignment_id, "status": assignment.status}


@router.get("/incident/{incident_id}/eta", response_model=list[EtaResponse])
def incident_etas(
    incident_id: str, session: Session = Depends(get_session)
) -> list[EtaResponse]:
    """Who is coming to this incident and how far away they are.

    Polled by the reporter's app to animate the responder's approach on the
    map. Only active assignments are returned -- a declined offer is not
    someone on their way.
    """
    incident = session.get(IncidentRow, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")

    active = {
        AssignmentStatus.ACCEPTED.value,
        AssignmentStatus.EN_ROUTE.value,
        AssignmentStatus.ON_SCENE.value,
    }

    results: list[EtaResponse] = []
    for assignment in incident.assignments:
        if assignment.status not in active:
            continue

        responder = assignment.responder
        distance_km = eta_minutes = None

        # Prefer the responder's live position over their base location: the
        # whole point of this endpoint is to show actual progress.
        latitude = responder.last_latitude or responder.latitude
        longitude = responder.last_longitude or responder.longitude

        if None not in (incident.latitude, incident.longitude, latitude, longitude):
            distance_km = round(
                haversine_km(incident.latitude, incident.longitude, latitude, longitude), 1
            )
            eta_minutes = round(estimate_drive_minutes(distance_km))

        results.append(
            EtaResponse(
                responder_id=responder.responder_id,
                name=responder.name,
                latitude=latitude,
                longitude=longitude,
                distance_km=distance_km,
                eta_minutes=eta_minutes,
                status=assignment.status,
            )
        )

    return results
