"""A coordinator's decision on an incoming incident.

Four options, each recorded on the incident's event history:

1. **Ignore** -- close it with a reason (below). Volunteer alerts still
   waiting on a reply are cancelled, so nobody heads to a closed case.
2. **Send a team** -- the existing `POST /responders/assign` offer. Not here.
3. **Send volunteers** -- `services.volunteers`.
4. **Send a drone** -- plan a survey over the incident with the existing
   drone planner. **Simulation only**: the planner never commands an aircraft,
   and nothing here changes that.
"""

from __future__ import annotations

import math

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifejacket.drones.planner import plan_mission
from lifejacket.models.coordinator import DecisionEntry, DroneSurveyOut, IgnoreResult
from lifejacket.models.drone import DroneMissionRequest, DronePoint, SurveyBox
from lifejacket.models.tables import (
    AssignmentRow,
    IncidentEventRow,
    IncidentRow,
    ResponderRow,
    VolunteerRow,
)
from lifejacket.services import volunteers
from lifejacket.services.assignment_summary import TERMINAL_CASES
from lifejacket.services.events import incident_state, record_event, record_incident_change

#: Reason -> (status it closes the case with, label). "Healthy animal" uses the
#: existing guidance-only status; every other reason is a cancellation.
IGNORE_REASONS: dict[str, tuple[str, str]] = {
    "false_report": ("cancelled", "false report"),
    "healthy_animal": ("guidance_only", "healthy animal, no response needed"),
    "duplicate": ("cancelled", "duplicate report"),
    "animal_left": ("cancelled", "animal has left"),
    "out_of_area": ("cancelled", "outside the network's area"),
    "other": ("cancelled", "other"),
}

#: A team that has said yes is on its way; ignoring would strand them.
_COMMITTED = {"accepted", "en_route", "on_scene"}

# Drone survey geometry. The launch point is east of the animal: on
# California's coast that is the landward side, and taking off on top of an
# animal is what a survey should avoid. The console says to confirm on site.
SURVEY_HALF_SIDE_M = 100.0
LAUNCH_OFFSET_M = 120.0
SURVEY_ALTITUDE_M = 60.0
_M_PER_DEG_LAT = 111_320.0


def ignore(
    session: Session, incident: IncidentRow, reason: str, note: str | None, decided_by: str
) -> IgnoreResult:
    if incident.status in TERMINAL_CASES:
        raise HTTPException(status_code=409, detail="This case is already closed")
    committed = session.scalars(
        select(AssignmentRow).where(
            AssignmentRow.incident_id == incident.incident_id,
            AssignmentRow.status.in_(_COMMITTED),
        )
    ).first()
    if committed is not None:
        raise HTTPException(
            status_code=409,
            detail="A team has accepted this case. Close it through the outcome log instead.",
        )

    status, _ = IGNORE_REASONS[reason]
    before = incident_state(incident)
    incident.status = status
    incident.updated_at = volunteers.utc_now()
    cancelled = volunteers.stand_down(session, incident.incident_id)
    record_event(
        session,
        incident.incident_id,
        "coordinator_ignored",
        {
            "reason": reason,
            "status": status,
            "note": (note or "").strip() or None,
            "volunteer_alerts_cancelled": cancelled,
        },
        decided_by,
    )
    record_incident_change(session, incident, before, decided_by)
    return IgnoreResult(
        incident_id=incident.incident_id,
        status=status,
        reason=reason,
        volunteer_alerts_cancelled=cancelled,
    )


def plan_drone_survey(
    session: Session, incident: IncidentRow, requested_by: str
) -> DroneSurveyOut:
    if incident.status in TERMINAL_CASES:
        raise HTTPException(status_code=409, detail="This case is closed")
    if incident.latitude is None or incident.longitude is None:
        raise HTTPException(status_code=409, detail="This incident has no location yet")

    lat, lon = incident.latitude, incident.longitude
    m_per_deg_lon = _M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01)
    dlat = SURVEY_HALF_SIDE_M / _M_PER_DEG_LAT
    dlon = SURVEY_HALF_SIDE_M / m_per_deg_lon
    try:
        mission = DroneMissionRequest(
            home=DronePoint(
                latitude=float(lat), longitude=float(lon + LAUNCH_OFFSET_M / m_per_deg_lon)
            ),
            survey_area=SurveyBox(
                south=float(lat - dlat),
                north=float(lat + dlat),
                west=float(lon - dlon),
                east=float(lon + dlon),
            ),
            altitude_m=SURVEY_ALTITUDE_M,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "The drone simulation only covers California, "
                "and this incident is outside it."
            ),
        ) from exc

    plan = plan_mission(mission)
    record_event(
        session,
        incident.incident_id,
        "drone_survey_planned",
        {
            "plan_id": plan.plan_id,
            "status": plan.status,
            "blocked_reasons": plan.blocked_reasons,
            "distance_m": plan.distance_m,
            "duration_s": plan.duration_s,
            "estimated_battery_remaining_percent": plan.estimated_battery_remaining_percent,
            "simulation_only": True,
        },
        requested_by,
    )
    area = mission.survey_area
    return DroneSurveyOut(
        incident_id=incident.incident_id,
        plan_id=plan.plan_id,
        status=plan.status,
        blocked_reasons=plan.blocked_reasons,
        home_latitude=mission.home.latitude,
        home_longitude=mission.home.longitude,
        survey_south=area.south,
        survey_north=area.north,
        survey_west=area.west,
        survey_east=area.east,
        altitude_m=mission.altitude_m,
        distance_m=plan.distance_m,
        duration_s=plan.duration_s,
        estimated_battery_remaining_percent=plan.estimated_battery_remaining_percent,
        waypoint_count=len(plan.waypoints),
        launch_note=(
            f"Launch point assumed {LAUNCH_OFFSET_M:.0f} m inland (east) of the animal. "
            "Confirm a safe take-off spot on site."
        ),
    )


# --- Decision log ------------------------------------------------------------

DECISION_KINDS = (
    "coordinator_ignored",
    "assignment_offered",
    "assignment_response",
    "volunteers_alerted",
    "volunteer_reply",
    "drone_survey_planned",
)


def decision_log(session: Session, incident_id: str) -> list[DecisionEntry]:
    events = session.scalars(
        select(IncidentEventRow)
        .where(
            IncidentEventRow.incident_id == incident_id,
            IncidentEventRow.kind.in_(DECISION_KINDS),
        )
        .order_by(IncidentEventRow.recorded_at, IncidentEventRow.id)
    ).all()
    return [
        DecisionEntry(
            event_id=event.id,
            kind=event.kind,
            summary=_summarise(session, event.kind, event.details or {}),
            actor=event.actor_ref,
            recorded_at=volunteers.as_utc(event.recorded_at),
        )
        for event in events
    ]


def _name(session: Session, model, key: str | None, fallback: str) -> str:
    row = session.get(model, key) if key else None
    return row.name if row is not None else fallback


def _summarise(session: Session, kind: str, d: dict) -> str:
    if kind == "coordinator_ignored":
        label = IGNORE_REASONS.get(d.get("reason", ""), ("", "other"))[1]
        text = f"Ignored: {label}"
        if d.get("volunteer_alerts_cancelled"):
            count = d["volunteer_alerts_cancelled"]
            text += f". Stood down {count} pending volunteer alert(s)"
        return text + (f'. Note: "{d["note"]}"' if d.get("note") else "")
    if kind == "assignment_offered":
        return f"Offered to {_name(session, ResponderRow, d.get('responder_id'), 'a team')}"
    if kind == "assignment_response":
        team = _name(session, ResponderRow, d.get("responder_id"), "The team")
        return f"{team} {'accepted' if d.get('after') == 'accepted' else 'declined'}"
    if kind == "volunteers_alerted":
        count = len(d.get("volunteer_ids") or [])
        task = "watch from a distance" if d.get("task") == "observe" else "support the team"
        return f"Alerted {count} volunteer(s) to {task} (simulated texts)"
    if kind == "volunteer_reply":
        who = _name(session, VolunteerRow, d.get("volunteer_id"), "A volunteer")
        return f"{who} {'checked in' if d.get('status') == 'checked_in' else 'cannot go'}"
    if kind == "drone_survey_planned":
        if d.get("status") == "blocked":
            reasons = "; ".join(d.get("blocked_reasons") or []) or "blocked"
            return f"Drone survey planned but blocked: {reasons} (simulation)"
        km = (d.get("distance_m") or 0) / 1000
        minutes = (d.get("duration_s") or 0) / 60
        return f"Drone survey planned: {km:.1f} km, about {minutes:.0f} min (simulation)"
    return kind
