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
POLICY_VERSION = "low-confidence-v3"


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


def confidence_summary(incident):
    assessment = incident.assessment_json
    injury = assessment.get("injury") if isinstance(assessment, dict) else None
    return {
        "animal_group": group_confidence(incident.identification_json),
        "condition": score(injury.get("confidence")) if isinstance(injury, dict) else None,
    }


def explicitly_unidentified(identity):
    if not isinstance(identity, dict):
        return False
    candidates = identity.get("candidates")
    if isinstance(candidates, list) and candidates:
        valid = [
            c
            for c in candidates
            if isinstance(c, dict) and score(c.get("confidence")) is not None
        ]
        if any(
            isinstance(c.get("animal_group"), str) and c["animal_group"] in GROUPS
            for c in valid
        ):
            return False
        if any(c.get("animal_group") == "unknown" for c in valid):
            return True
    resolution = identity.get("resolution")
    if isinstance(resolution, dict) and resolution.get("rank") == "unknown":
        return True
    return candidates == [] and identity.get("needs_new_photo") is True


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
    if animal_score is None and explicitly_unidentified(identity):
        signals.append(
            {
                "code": "identification_evidence_gap",
                "label": "Animal group unresolved",
                "confidence": None,
                "reason": (
                    "The animal remains unidentified after intake; "
                    "a clearer view needs review."
                ),
            }
        )
    photo_requested = isinstance(identity, dict) and identity.get("needs_new_photo") is True
    if photo_requested:
        signals.append(
            {
                "code": "photo_evidence_gap",
                "label": "Clearer photo requested",
                "confidence": None,
                "reason": (
                    "Intake explicitly requests another photo; "
                    "the available view needs review even if confidence is high."
                ),
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
    if any(
        s["code"] in {"animal_group_uncertain", "identification_evidence_gap"} for s in signals
    ):
        objectives.append("Clarify the animal group from an additional view")
    if photo_requested:
        objectives.append(
            "Obtain a clearer view of the reported animal for coordinator review"
        )
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
        "title": (
            "Clearer photo requested"
            if photo_requested and len(signals) == 1
            else "Additional evidence suggested"
        ),
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
                "Review whether a clearer reporter photo, ground observation or drone "
                "evidence is appropriate before creating a request."
                if photo_requested
                else "Coordinator review is required before creating a request "
                "or arranging a flight."
            )
        ),
        "escalation_criteria": (
            "Escalate any new signs of distress or worsening hazards to the lead coordinator."
        ),
    }
