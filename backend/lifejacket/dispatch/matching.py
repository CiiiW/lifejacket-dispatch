"""Choosing which rescue organisation or volunteer to send.

Scoring combines two things, weighted in `config/scoring.json`:

- **Area coverage** (0.58). Does this organisation operate where the animal is?
  Matched against the free-text `response_area` from the stranding-network
  directory, using the county resolved by reverse geocoding.
- **Capability** (0.42). Are they permitted and equipped for this animal and
  this situation? A dead-animal-only centre must not be sent to a live rescue;
  an entanglement needs a team with cutting authorisation.

Distance is used to order and to estimate an ETA, but it is not part of the
match score. That is deliberate: a nearby organisation with no permit for the
species is not a better match than a qualified one an hour away. Sending the
wrong team wastes the animal's time, not just the responder's.

**Nothing here dispatches anyone.** It produces a ranked, justified list for a
human coordinator to approve. That gate is a requirement of how stranding
networks operate, not a limitation of the system.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache

from lifejacket.config import DATA_DIR, load_scoring_config
from lifejacket.geo import estimate_drive_minutes, haversine_km
from lifejacket.models.schemas import (
    AnimalGroup,
    DispatchCandidate,
    InjuryAssessment,
    MobilityConcern,
    RescueCenter,
    ResponderKind,
)

#: Words in a directory `response_type` that indicate each capability. The
#: directory is free text written by many different people, so matching is by
#: keyword rather than by parsing.
_LIVE_RESPONSE_TERMS = ("live", "rescue", "rehabilitation", "rehab")
_DEAD_RESPONSE_TERMS = ("dead", "carcass", "necropsy", "salvage")
_ENTANGLEMENT_TERMS = ("entanglement", "disentanglement", "entangled")
_TRANSPORT_TERMS = ("transport",)
_REHAB_TERMS = ("rehabilitation", "rehab")

#: Species-group keywords as they appear in `response_type` text.
#:
#: TERRESTRIAL and DOMESTIC_ANIMAL are deliberately absent: the directory is
#: the West Coast Marine Mammal Stranding Network, which has no permit or
#: equipment for a coyote or a pet dog. `rank_centers` below refuses to match
#: those groups at all, rather than let them fall through to a weak
#: area-only match -- see `_UNSUPPORTED_GROUPS`.
_GROUP_TERMS: dict[AnimalGroup, tuple[str, ...]] = {
    AnimalGroup.PINNIPED: ("pinniped", "seal", "sea lion"),
    AnimalGroup.CETACEAN: ("cetacean", "whale", "dolphin", "porpoise"),
    AnimalGroup.SEA_TURTLE: ("sea turtle", "turtle"),
    AnimalGroup.SEABIRD: ("bird", "seabird", "avian"),
    # No centre names an otter or manatee specifically, but several describe
    # themselves generically as "marine mammal" responders, which is the
    # closest honest match a sea otter or similar animal can get today.
    AnimalGroup.OTHER_MARINE: ("marine mammal", "marine animal", "otter", "manatee"),
}

#: Groups this directory has no real capability for at all. Matched only on
#: area, a Monterey Bay seal centre would otherwise look like a plausible
#: (if weak) match for a reported coyote -- which is actively misleading, so
#: these groups are refused before scoring even starts.
_UNSUPPORTED_GROUPS = frozenset({AnimalGroup.TERRESTRIAL, AnimalGroup.DOMESTIC_ANIMAL})


@lru_cache(maxsize=1)
def load_rescue_centers() -> list[RescueCenter]:
    """Read `data/rescue_centers.csv` into typed records.

    Source is the public 2026 West Coast Marine Mammal Stranding Network
    directory. Cached for the process lifetime; it changes annually.
    """
    path = DATA_DIR / "rescue_centers.csv"
    centers: list[RescueCenter] = []

    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            # Blank strings from CSV become None so that optional fields read
            # as genuinely absent rather than empty.
            cleaned = {
                key: (value.strip() or None) if isinstance(value, str) else value
                for key, value in row.items()
            }
            centers.append(RescueCenter(**cleaned))

    return centers


def score_area_match(response_area: str | None, area_terms: list[str]) -> float:
    """How well an organisation's coverage area matches the incident location.

    Args:
        response_area: Free text, e.g. "Del Norte and Humboldt Counties, California".
        area_terms: Lower-cased terms from reverse geocoding, e.g.
            `["humboldt", "eureka", "california"]`.

    Returns:
        0.0 for no overlap, otherwise 0.55 plus 0.15 per matching term, capped
        at 1.0. The large base reflects that *any* genuine area match is strong
        evidence; extra terms refine an already-good match.
    """
    if not response_area or not area_terms:
        return 0.0

    area_lower = response_area.lower()
    matched = [term for term in area_terms if term and term in area_lower]
    if not matched:
        return 0.0

    config = load_scoring_config()["dispatch"]
    score = (
        config["area_match_base_score"]
        + config["area_match_per_term_score"] * len(matched)
    )
    return min(score, 1.0)


def score_capability_match(
    response_type: str | None,
    animal_group: AnimalGroup,
    needs_live_response: bool,
    injury: InjuryAssessment,
) -> tuple[float, list[str]]:
    """Score whether an organisation can handle this animal and situation.

    Returns the score (0-1) and the list of matched capability names, which
    becomes the human-readable rationale.
    """
    if not response_type:
        return 0.0, []

    config = load_scoring_config()["dispatch"]
    type_lower = response_type.lower()
    score = 0.0
    matched: list[str] = []

    # --- Species permit ---
    group_terms = _GROUP_TERMS.get(animal_group, ())
    if group_terms and any(term in type_lower for term in group_terms):
        score += config["species_capability_score"]
        matched.append(f"{animal_group.value} response")
    elif animal_group is AnimalGroup.UNKNOWN and "marine mammal" in type_lower:
        # With an unidentified animal, a general marine-mammal responder is the
        # safest choice -- they can identify it on arrival and escalate.
        score += config["unknown_species_general_score"]
        matched.append("general marine mammal response")

    # --- Live vs dead ---
    handles_live = any(term in type_lower for term in _LIVE_RESPONSE_TERMS)
    handles_dead = any(term in type_lower for term in _DEAD_RESPONSE_TERMS)

    if needs_live_response:
        if handles_live:
            score += config["response_need_score"]
            matched.append("live animal response")
        elif handles_dead:
            # A carcass-recovery-only organisation sent to a living animal is a
            # serious mismatch, so this is an explicit penalty rather than
            # merely a missing bonus.
            score -= config["dead_only_mismatch_penalty"]
    elif handles_dead:
        score += config["response_need_score"]
        matched.append("deceased animal recovery")

    # --- Situation-specific equipment ---
    if injury.entanglement and any(term in type_lower for term in _ENTANGLEMENT_TERMS):
        score += config["entanglement_score"]
        matched.append("entanglement / disentanglement")

    if any(term in type_lower for term in _REHAB_TERMS):
        score += config["rehabilitation_score"]
        matched.append("rehabilitation facility")

    if any(term in type_lower for term in _TRANSPORT_TERMS):
        score += config["transport_score"]
        matched.append("transport")

    return max(0.0, min(score, 1.0)), matched


def infer_needs_live_response(injury: InjuryAssessment) -> bool:
    """Whether this is a live-animal call.

    Conservative by design: an animal is only treated as deceased when it is
    both unresponsive *and* immobile. Everything else -- including "unknown" --
    is a live call, because sending a carcass-recovery team to a living animal
    is by far the costlier mistake.

    Note that we deliberately do not infer death from the absence of
    respiratory distress. A false `respiratory_distress` flag means no distress
    was *observed*, which is not evidence that the animal has stopped
    breathing. Only a trained responder on scene can make that call.
    """
    appears_deceased = (
        injury.unresponsive and injury.mobility_concern is MobilityConcern.IMMOBILE
    )
    return not appears_deceased


def rank_centers(
    area_terms: list[str],
    animal_group: AnimalGroup,
    injury: InjuryAssessment,
    latitude: float | None = None,
    longitude: float | None = None,
    limit: int = 5,
) -> list[DispatchCandidate]:
    """Rank rescue organisations for an incident, best match first.

    Args:
        area_terms: From `context.geocode.reverse_geocode(...).area_terms`.
        animal_group: Drives the species-permit component.
        injury: Drives equipment matching (entanglement in particular).
        latitude, longitude: Used for distance and ETA only, not for scoring.
        limit: How many candidates to return.

    Returns:
        Candidates scoring above the configured minimum, highest first. An
        empty list is a meaningful result: either no organisation in the
        directory covers this location, or (for `TERRESTRIAL` and
        `DOMESTIC_ANIMAL`) this directory has no capability for the animal
        at all, so the coordinator must escalate manually rather than be
        shown a misleading marine-mammal match.
    """
    if animal_group in _UNSUPPORTED_GROUPS:
        return []

    config = load_scoring_config()["dispatch"]
    weights = config["scoring_weights"]
    needs_live = infer_needs_live_response(injury)

    candidates: list[DispatchCandidate] = []

    for center in load_rescue_centers():
        area_score = score_area_match(center.response_area, area_terms)
        capability_score, matched = score_capability_match(
            center.response_type, animal_group, needs_live, injury
        )

        total = weights["area"] * area_score + weights["capability"] * capability_score
        if total <= 0:
            continue

        distance_km: float | None = None
        eta_minutes: float | None = None
        if None not in (latitude, longitude, center.latitude, center.longitude):
            distance_km = round(
                haversine_km(latitude, longitude, center.latitude, center.longitude), 1
            )
            eta_minutes = round(estimate_drive_minutes(distance_km))

        candidates.append(
            DispatchCandidate(
                responder_id=center_id(center.center_name),
                name=center.center_name,
                kind=ResponderKind.ORGANISATION,
                score=round(min(total, 1.0), 2),
                distance_km=distance_km,
                eta_minutes=eta_minutes,
                rationale=_build_rationale(center, area_score, matched, distance_km),
                matched_capabilities=matched,
                contact_phone=center.hotline or center.phone,
                contact_email=center.email,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    minimum = config["alternate_min_confidence"]

    # Always return the single best option even if it is weak -- a poor match
    # with a clear rationale is more useful to a coordinator than nothing.
    strong = [c for c in candidates if c.score >= minimum]
    return (strong or candidates[:1])[:limit]


def _build_rationale(
    center: RescueCenter,
    area_score: float,
    matched_capabilities: list[str],
    distance_km: float | None,
) -> str:
    """One sentence explaining why this organisation was suggested.

    Shown beside the score in the console, so the coordinator approves a
    reason rather than a number.
    """
    parts: list[str] = []

    if area_score > 0 and center.response_area:
        area = center.response_area
        parts.append(f"covers {area[:80]}{'...' if len(area) > 80 else ''}")
    else:
        parts.append("no explicit area match in the directory")

    if matched_capabilities:
        parts.append("capable of " + ", ".join(matched_capabilities))
    else:
        parts.append("capabilities unclear from the directory listing")

    if distance_km is not None:
        parts.append(f"{distance_km:.0f} km from the incident")

    return "; ".join(parts)


def center_id(name: str) -> str:
    """Stable identifier derived from the organisation's name.

    Derived rather than assigned because the directory CSV has no ID column,
    and a name-derived key stays consistent across reloads.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"org_{slug[:48]}"
