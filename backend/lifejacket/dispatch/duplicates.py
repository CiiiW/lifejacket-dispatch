"""Detecting when two reports describe the same animal.

A stranded animal on a public beach gets reported repeatedly -- by every person
who walks past. Without duplicate detection, one sea lion generates fifteen
incidents and the responder map becomes unreadable.

The approach is a weighted score over three signals, from
`config/scoring.json`:

- **Distance** (weight 0.45). The strongest signal. Two reports 50 m apart are
  almost certainly the same animal; 5 km apart, almost certainly not.
- **Time** (weight 0.35). Reports hours apart are less likely to match, since
  animals move and are removed.
- **Species agreement** (weight 0.20). Weakest, because two reporters commonly
  describe the same animal differently -- so a mismatch is only a partial
  penalty, never disqualifying.

Duplicates are **linked, not deleted**. Two independent reports are useful
corroboration that something is really there, and the second reporter may have
supplied a better photo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from lifejacket.config import load_scoring_config
from lifejacket.geo import haversine_km
from lifejacket.models.schemas import AnimalGroup, DuplicateMatch


@dataclass
class CandidateIncident:
    """The minimum needed to compare an existing incident against a new one."""

    incident_id: str
    latitude: float | None
    longitude: float | None
    reported_at: datetime
    animal_group: AnimalGroup = AnimalGroup.UNKNOWN
    species_common_name: str | None = None


def duplicate_confidence(
    distance_km: float, hours_apart: float, species_match: bool
) -> float:
    """Score how likely two reports are the same animal, from 0 to 1.

    Distance and time decay linearly to zero at their configured cut-offs, so a
    report at exactly the distance limit contributes nothing from that signal
    while still being scoreable on the others.
    """
    config = load_scoring_config()["duplicate_matching"]
    weights = config["confidence_weights"]

    distance_component = max(0.0, 1.0 - distance_km / config["distance_km"])
    time_component = max(0.0, 1.0 - hours_apart / config["time_hours"])
    # A species mismatch scores 0.35 rather than 0, because reporters describe
    # the same animal inconsistently and we do not want that to veto a strong
    # distance-and-time match.
    species_component = 1.0 if species_match else 0.35

    return round(
        weights["distance"] * distance_component
        + weights["time"] * time_component
        + weights["species"] * species_component,
        3,
    )


def find_duplicate(
    latitude: float | None,
    longitude: float | None,
    reported_at: datetime,
    animal_group: AnimalGroup,
    candidates: list[CandidateIncident],
) -> DuplicateMatch | None:
    """Best duplicate match for a new report, or None.

    Only candidates inside **both** the distance and time windows are scored at
    all -- the windows are a hard gate, and the weighted score then ranks what
    survives. Without the gate, a distant report could still score moderately
    on time and species alone.

    Returns None when the location is unknown, since distance is the signal
    doing most of the work and we would rather not guess.
    """
    if latitude is None or longitude is None:
        return None

    config = load_scoring_config()["duplicate_matching"]
    max_distance = config["distance_km"]
    max_hours = config["time_hours"]

    best: DuplicateMatch | None = None

    for candidate in candidates:
        if candidate.latitude is None or candidate.longitude is None:
            continue

        distance = haversine_km(
            latitude, longitude, candidate.latitude, candidate.longitude
        )
        if distance > max_distance:
            continue

        hours = abs((reported_at - candidate.reported_at).total_seconds()) / 3600.0
        if hours > max_hours:
            continue

        # An unknown group is treated as compatible with anything: we have no
        # evidence of a mismatch, so we should not penalise for one.
        species_match = (
            animal_group is AnimalGroup.UNKNOWN
            or candidate.animal_group is AnimalGroup.UNKNOWN
            or animal_group == candidate.animal_group
        )

        confidence = duplicate_confidence(distance, hours, species_match)

        if best is None or confidence > best.confidence:
            best = DuplicateMatch(
                incident_id=candidate.incident_id,
                confidence=confidence,
                distance_km=round(distance, 3),
                hours_apart=round(hours, 2),
                same_species=species_match,
                reason=(
                    f"{distance * 1000:.0f} m away, reported {hours:.1f} hours earlier, "
                    f"{'same' if species_match else 'different'} animal group"
                ),
            )

    return best


def is_probable_duplicate(match: DuplicateMatch | None) -> bool:
    """Whether a match is strong enough to suppress a second dispatch.

    Below the threshold the incident is still flagged for the coordinator as a
    *possible* duplicate, but it is dispatched normally. Missing a real animal
    is a worse error than sending a responder to an animal already being helped.
    """
    if match is None:
        return False
    threshold = load_scoring_config()["duplicate_matching"]["probable_duplicate_threshold"]
    return match.confidence >= threshold
