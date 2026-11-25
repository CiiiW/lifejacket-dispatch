"""Nearby volunteers, and the alerts that ask them to check in.

The rules come from `docs/reporter_participation.md`:

- **An alert is an invitation, not an assignment**, and sending one is not
  proof it arrived. With no SMS provider configured, every alert is recorded
  with `delivery="simulated"` and the volunteer's reply is recorded by hand.
- **Watching and hands-on work need different people.** A monitor-level case
  asks volunteers to watch from a distance, which any opted-in volunteer can
  do. A respond- or critical-level case asks them to support a team on
  arrival, which needs a trained responder. Volunteers support a team; they
  are never a substitute for one.
- **No statewide volunteer map.** The console only ever sees volunteers near
  the incident it is looking at, and never their phone numbers.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from lifejacket.config import DATA_DIR
from lifejacket.geo import haversine_km
from lifejacket.models.coordinator import (
    NearbyVolunteer,
    NearbyVolunteers,
    VolunteerAlertBrief,
    VolunteerAlertOut,
    VolunteerSummary,
)
from lifejacket.models.tables import IncidentRow, VolunteerAlertRow, VolunteerRow
from lifejacket.services.assignment_summary import TERMINAL_CASES
from lifejacket.services.events import record_event

SEED_PATH = DATA_DIR / "seeds" / "demo_volunteers.json"

#: Volunteers further than this from the incident are never returned.
SEARCH_RADIUS_KM = 60.0

TRAINED = "trained_responder"
#: Alerts still waiting on, or already holding, a volunteer's yes.
OPEN_ALERT_STATUSES = {"awaiting_reply", "checked_in"}

TASK_DESCRIPTIONS = {
    "observe": (
        "Watch from a safe distance, keep people and dogs back, and report changes."
    ),
    "support": (
        "Support the rescue team on arrival. Volunteers assist a team; they do "
        "not replace one."
    ),
}


def utc_now() -> datetime:
    """Naive UTC, matching `services.events.record_event`."""
    return datetime.now(UTC).replace(tzinfo=None)


def as_utc(value: datetime | None) -> datetime | None:
    """Stored naive UTC, returned with its offset so a client parses it right."""
    return value.replace(tzinfo=UTC) if value is not None else None


def task_for(severity_level: str | None) -> str:
    """What a volunteer is asked to do, from the triage band."""
    return "support" if severity_level in {"respond", "critical"} else "observe"


def ineligible_reason(volunteer: VolunteerRow, task: str, distance_km: float) -> str | None:
    """Why this volunteer cannot be alerted for this task, or None if they can."""
    if not volunteer.available:
        return "Has paused alerts"
    if distance_km > volunteer.travel_radius_km:
        return f"Outside their {volunteer.travel_radius_km:g} km travel radius"
    if task == "support" and volunteer.qualification != TRAINED:
        return "Hands-on support needs a trained responder"
    return None


def _located(incident: IncidentRow) -> tuple[float, float]:
    if incident.latitude is None or incident.longitude is None:
        raise HTTPException(status_code=409, detail="This incident has no location yet")
    return incident.latitude, incident.longitude


def _open_case(incident: IncidentRow) -> None:
    if incident.status in TERMINAL_CASES:
        raise HTTPException(status_code=409, detail="This case is closed")


def get_incident(session: Session, incident_id: str) -> IncidentRow:
    incident = session.get(IncidentRow, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")
    return incident


def _latest_alerts(session: Session, incident_id: str) -> dict[str, VolunteerAlertRow]:
    rows = session.scalars(
        select(VolunteerAlertRow)
        .where(VolunteerAlertRow.incident_id == incident_id)
        .order_by(VolunteerAlertRow.id)
    )
    return {row.volunteer_id: row for row in rows}  # later rows win


def nearby(session: Session, incident: IncidentRow) -> NearbyVolunteers:
    """Volunteers within SEARCH_RADIUS_KM of the incident, nearest first."""
    task = task_for(incident.severity_level)
    result = NearbyVolunteers(
        incident_id=incident.incident_id,
        task=task,
        task_description=TASK_DESCRIPTIONS[task],
        search_radius_km=SEARCH_RADIUS_KM,
        volunteers=[],
    )
    if incident.latitude is None or incident.longitude is None:
        return result
    lat, lon = incident.latitude, incident.longitude

    # A bounding box first, so the query never reads the whole table.
    dlat = SEARCH_RADIUS_KM / 111.0
    dlon = SEARCH_RADIUS_KM / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    candidates = session.scalars(
        select(VolunteerRow).where(
            VolunteerRow.latitude.between(lat - dlat, lat + dlat),
            VolunteerRow.longitude.between(lon - dlon, lon + dlon),
        )
    )
    alerts = _latest_alerts(session, incident.incident_id)
    for volunteer in candidates:
        distance = haversine_km(lat, lon, volunteer.latitude, volunteer.longitude)
        if distance > SEARCH_RADIUS_KM:
            continue
        reason = ineligible_reason(volunteer, task, distance)
        alert = alerts.get(volunteer.volunteer_id)
        result.volunteers.append(
            NearbyVolunteer(
                volunteer_id=volunteer.volunteer_id,
                name=volunteer.name,
                address=volunteer.address,
                latitude=volunteer.latitude,
                longitude=volunteer.longitude,
                qualification=volunteer.qualification,
                travel_radius_km=volunteer.travel_radius_km,
                skills=list(volunteer.skills or []),
                available=volunteer.available,
                phone_last4=volunteer.phone[-4:],
                distance_km=round(distance, 1),
                in_range=distance <= volunteer.travel_radius_km,
                eligible=reason is None,
                ineligible_reason=reason,
                alert=(
                    VolunteerAlertBrief(alert_id=alert.id, status=alert.status)
                    if alert
                    else None
                ),
                fictional=volunteer.is_fictional,
            )
        )
    result.volunteers.sort(key=lambda v: v.distance_km)
    return result


def alert_out(alert: VolunteerAlertRow, volunteer: VolunteerRow) -> VolunteerAlertOut:
    return VolunteerAlertOut(
        alert_id=alert.id,
        incident_id=alert.incident_id,
        volunteer_id=alert.volunteer_id,
        volunteer_name=volunteer.name,
        phone_last4=volunteer.phone[-4:],
        task=alert.task,
        message=alert.message,
        status=alert.status,
        delivery=alert.delivery,
        distance_km=alert.distance_km,
        sent_at=as_utc(alert.sent_at),
        responded_at=as_utc(alert.responded_at),
        response_note=alert.response_note,
    )


def list_alerts(session: Session, incident_id: str) -> list[VolunteerAlertOut]:
    rows = session.execute(
        select(VolunteerAlertRow, VolunteerRow)
        .join(VolunteerRow, VolunteerRow.volunteer_id == VolunteerAlertRow.volunteer_id)
        .where(VolunteerAlertRow.incident_id == incident_id)
        .order_by(VolunteerAlertRow.id)
    )
    return [alert_out(alert, volunteer) for alert, volunteer in rows]


def send_alerts(
    session: Session,
    incident: IncidentRow,
    volunteer_ids: list[str],
    message: str,
    sent_by: str,
) -> list[VolunteerAlertOut]:
    """Alert each volunteer to check in. All or nothing: one bad ID sends none."""
    _open_case(incident)
    lat, lon = _located(incident)
    text = message.strip()
    if not text:
        raise HTTPException(status_code=422, detail="The alert message is empty")
    if len(set(volunteer_ids)) != len(volunteer_ids):
        raise HTTPException(status_code=422, detail="A volunteer is listed twice")

    task = task_for(incident.severity_level)
    existing = _latest_alerts(session, incident.incident_id)
    chosen: list[tuple[VolunteerRow, float]] = []
    for volunteer_id in volunteer_ids:
        volunteer = session.get(VolunteerRow, volunteer_id)
        if volunteer is None:
            raise HTTPException(status_code=404, detail=f"Unknown volunteer: {volunteer_id}")
        distance = haversine_km(lat, lon, volunteer.latitude, volunteer.longitude)
        reason = ineligible_reason(volunteer, task, distance)
        if reason:
            raise HTTPException(status_code=422, detail=f"{volunteer.name}: {reason}")
        previous = existing.get(volunteer_id)
        if previous is not None and previous.status in OPEN_ALERT_STATUSES:
            raise HTTPException(
                status_code=409, detail=f"{volunteer.name} has already been alerted"
            )
        chosen.append((volunteer, distance))

    now = utc_now()
    rows = [
        VolunteerAlertRow(
            incident_id=incident.incident_id,
            volunteer_id=volunteer.volunteer_id,
            task=task,
            message=text,
            status="awaiting_reply",
            # No SMS provider exists in this codebase, so nothing is ever sent.
            delivery="simulated",
            distance_km=round(distance, 1),
            sent_by=sent_by,
            sent_at=now,
        )
        for volunteer, distance in chosen
    ]
    session.add_all(rows)
    session.flush()
    # Message text stays out of the event: event details reach the
    # coordination agent's prompt as observations.
    record_event(
        session,
        incident.incident_id,
        "volunteers_alerted",
        {
            "alert_ids": [row.id for row in rows],
            "volunteer_ids": [row.volunteer_id for row in rows],
            "task": task,
            "delivery": "simulated",
        },
        sent_by,
    )
    return [
        alert_out(row, volunteer)
        for row, (volunteer, _) in zip(rows, chosen, strict=True)
    ]


def record_reply(
    session: Session, alert_id: int, status: str, note: str | None, recorded_by: str
) -> VolunteerAlertOut:
    """Record a volunteer's answer. Repeating the same answer is a no-op."""
    alert = session.get(VolunteerAlertRow, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Unknown alert: {alert_id}")
    volunteer = session.get(VolunteerRow, alert.volunteer_id)
    if alert.status == status:
        return alert_out(alert, volunteer)
    if alert.status != "awaiting_reply":
        raise HTTPException(status_code=409, detail=f"This alert is already {alert.status}")
    _open_case(get_incident(session, alert.incident_id))

    alert.status = status
    alert.responded_at = utc_now()
    alert.response_note = (note or "").strip() or None
    record_event(
        session,
        alert.incident_id,
        "volunteer_reply",
        {"alert_id": alert.id, "volunteer_id": alert.volunteer_id, "status": status},
        recorded_by,
    )
    return alert_out(alert, volunteer)


def stand_down(session: Session, incident_id: str) -> int:
    """Cancel alerts still awaiting a reply, when the case is ignored."""
    rows = session.scalars(
        select(VolunteerAlertRow).where(
            VolunteerAlertRow.incident_id == incident_id,
            VolunteerAlertRow.status == "awaiting_reply",
        )
    ).all()
    for row in rows:
        row.status = "cancelled"
    return len(rows)


def seed_demo_volunteers(session: Session) -> VolunteerSummary:
    """Load the fictional volunteers. Idempotent: existing IDs are left alone."""
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for entry in data["volunteers"]:
        if session.get(VolunteerRow, entry["volunteer_id"]) is None:
            session.add(VolunteerRow(**entry, is_fictional=True, created_at=utc_now()))
    session.flush()
    return summary(session)


def summary(session: Session) -> VolunteerSummary:
    total, available, fictional = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(VolunteerRow.available.cast(Integer)), 0),
            func.coalesce(func.sum(VolunteerRow.is_fictional.cast(Integer)), 0),
        ).select_from(VolunteerRow)
    ).one()
    return VolunteerSummary(total=total, available=available, fictional=fictional)
