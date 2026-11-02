"""Minimal own-report response contract, not wired to the legacy ETA endpoint yet."""

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from lifejacket.access.policy import CaseAccess, Principal, owns_report


class ResponsePhase(StrEnum):
    RECEIVED = "received"
    ACCEPTED = "accepted"
    EN_ROUTE = "en_route"
    ON_SCENE = "on_scene"
    ANIMAL_LOCATED = "animal_located"
    CLOSED = "closed"


@dataclass(frozen=True)
class ArrivalEstimate:
    minutes: float
    updated_at: datetime
    valid_until: datetime
    basis: str


def reporter_update(
    actor: Principal,
    case: CaseAccess,
    phase: ResponsePhase,
    *,
    now: datetime,
    arrival: ArrivalEstimate | None = None,
) -> dict:
    """Caller derives phase from confirmed case events, never model detections.

    Do not pass a raw IncidentDetail/Responder row through to the reporter. All
    output fields are enumerated here so new internal fields cannot leak by default.
    """
    if not owns_report(actor, case):
        raise PermissionError("Own-report access required")
    if not isinstance(phase, ResponsePhase):
        raise ValueError("Unknown response phase")
    if now.utcoffset() is None:
        raise ValueError("Use timezone-aware server time")
    messages = {
        ResponsePhase.RECEIVED: "Report received; awaiting team confirmation.",
        ResponsePhase.ACCEPTED: "A team has taken your report.",
        ResponsePhase.EN_ROUTE: "A team is on the way.",
        ResponsePhase.ON_SCENE: "The team has arrived and is checking the area.",
        ResponsePhase.ANIMAL_LOCATED: "The team has located the animal.",
        ResponsePhase.CLOSED: "A case outcome has been recorded.",
    }
    eta = updated = basis = None
    if phase == ResponsePhase.EN_ROUTE and case.active and arrival is not None:
        aware = (
            arrival.updated_at.utcoffset() is not None
            and arrival.valid_until.utcoffset() is not None
        )
        numeric = (
            not isinstance(arrival.minutes, bool)
            and isinstance(arrival.minutes, (int, float))
            and math.isfinite(arrival.minutes)
            and arrival.minutes >= 0
        )
        if (
            aware
            and numeric
            and arrival.updated_at <= now <= arrival.valid_until
            and arrival.basis in {"manual", "route_estimate", "rough_distance"}
        ):
            eta, updated, basis = (
                arrival.minutes,
                arrival.updated_at.isoformat(),
                arrival.basis,
            )
    return {
        "case_id": case.case_id,
        "phase": phase.value,
        "message": messages[phase],
        "arrival_eta_minutes": eta,
        "eta_updated_at": updated,
        "eta_basis": basis,
        "eta_is_estimate": eta is not None,
        "reporter_can_leave": True,
        "leaving_cancels_report": False,
    }
