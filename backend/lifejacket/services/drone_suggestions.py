"""Read-only, deterministic suggestions from explicit intake confidence evidence.

The threshold is provisional. No recommendation is a flight authorization,
diagnosis, or calibrated probability of being correct.
"""

import hashlib
import json
import math

GROUPS = {
    "pinniped",
    "cetacean",
    "sea_turtle",
    "seabird",
    "other_marine",
    "terrestrial",
    "domestic_animal",
}
FINAL_STATUSES = {
    "awaiting_dispatch",
    "dispatched",
    "accepted",
    "en_route",
    "on_scene",
    "guidance_only",
}
POLICY_VERSION = "low-confidence-v1"


def score(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value) if 0 <= value <= 1 else None


def group_confidence(identification):
    """Pool candidate probabilities by routing group, never exact species."""
    if not isinstance(identification, dict):
        return None
    candidates = identification.get("candidates")
    if isinstance(candidates, list) and candidates:
        totals = {}
        total = 0.0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                return None
            confidence = score(candidate.get("confidence"))
            if confidence is None:
                return None
            total += confidence
            group = candidate.get("animal_group")
            if isinstance(group, str) and group in GROUPS:
                totals[group] = totals.get(group, 0.0) + confidence
        if total > 1.000001:
            return None
        # Missing/unknown group probabilities do not identify a routing group.
        if totals:
            return min(1.0, round(max(totals.values()), 12))
        return None
    resolution = identification.get("resolution")
    if (
        isinstance(resolution, dict)
        and resolution.get("rank") == "group"
        and isinstance(resolution.get("animal_group"), str)
        and resolution.get("animal_group") in GROUPS
    ):
        return score(resolution.get("confidence"))
    return None


def suggest(incident, threshold):
    """One combined verification suggestion; absent/invalid scores stay unknown."""
    if incident.status not in FINAL_STATUSES or incident.duplicate_of:
        return None
    identity = incident.identification_json
    assessment = incident.assessment_json
    animal_score = group_confidence(identity)
    injury = assessment.get("injury") if isinstance(assessment, dict) else None
    condition_score = score(injury.get("confidence")) if isinstance(injury, dict) else None
    signals = []
    if animal_score is not None and animal_score < threshold:
        signals.append(
            {
                "code": "animal_group_uncertain",
                "label": "Animal group confidence",
                "confidence": animal_score,
                "reason": "The animal group remains uncertain after intake.",
            }
        )
    if condition_score is not None and condition_score < threshold:
        signals.append(
            {
                "code": "condition_uncertain",
                "label": "Condition assessment confidence",
                "confidence": condition_score,
                "reason": "The condition assessment remains uncertain after intake.",
            }
        )
    if not signals:
        return None
    urgent = incident.severity_level in {"critical", "respond"} or bool(
        incident.entanglement_present
        or (
            isinstance(injury, dict)
            and any(
                injury.get(k) is True
                for k in (
                    "entanglement",
                    "bleeding",
                    "respiratory_distress",
                    "unresponsive",
                )
            )
        )
    )
    objectives = []
    if any(s["code"] == "animal_group_uncertain" for s in signals):
        objectives.append("Clarify the animal group from an additional view")
    if any(s["code"] == "condition_uncertain" for s in signals):
        objectives.append(
            "Document visible posture, movement and possible entanglement for review"
        )
    evidence = {
        "identification": identity,
        "assessment": assessment,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "severity_level": incident.severity_level,
        "entanglement_present": incident.entanglement_present,
        "policy_version": POLICY_VERSION,
        "threshold": threshold,
    }
    fingerprint = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=True).encode()
    ).hexdigest()
    return {
        "suggestion_id": fingerprint,
        "purpose": "verification",
        "title": "Additional evidence suggested",
        "objective": "; ".join(objectives) + ".",
        "reason": " ".join(s["reason"] for s in signals),
        "signals": signals,
        "threshold": threshold,
        "threshold_is_validated": False,
        "policy_version": POLICY_VERSION,
        "urgent_parallel_review": urgent,
        "response_note": (
            "Continue urgent coordinator response review; do not wait for drone evidence."
            if urgent
            else (
                "Coordinator review is required before creating a request "
                "or arranging a flight."
            )
        ),
        "escalation_criteria": (
            "Escalate any new signs of distress or worsening hazards to the lead coordinator."
        ),
    }
