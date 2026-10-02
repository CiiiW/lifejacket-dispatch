"""Triage scoring: how urgent is this incident?

**This is deterministic Python, not an LLM call, and that is deliberate.**

The language model decides *what it observes* (is there a wound? is the animal
breathing normally?). This module decides *what that means* for urgency. The
split matters for three reasons:

- **Auditability.** A coordinator can be shown exactly which flags fired and
  what each contributed. "The model said critical" is not a reviewable answer.
- **Stability.** Changing a prompt should not silently re-tune triage
  thresholds for every incident in the system.
- **Testability.** Scoring is a pure function, so the test suite pins its
  behaviour without needing an API key.

The prototype's own prompt said "Do not use weather for this first prototype"
while a parallel deterministic path did use it, so the two disagreed. Here
there is one path, and the LLM's role is to write the human-readable rationale
for a decision this module has already made.

Weights and thresholds all come from `config/scoring.json`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lifejacket.config import load_scoring_config
from lifejacket.context.weather import weather_risk_score
from lifejacket.models.schemas import (
    AnimalGroup,
    EnvironmentalContext,
    InjuryAssessment,
    MobilityConcern,
    SeverityLevel,
    SituationHazards,
)

#: Numeric level to enum, matching the prototype's 0-3 scale so that existing
#: research data remains comparable.
_LEVEL_ORDER: list[SeverityLevel] = [
    SeverityLevel.GUIDANCE,  # 0
    SeverityLevel.MONITOR,  # 1
    SeverityLevel.RESPOND,  # 2
    SeverityLevel.CRITICAL,  # 3
]


@dataclass
class SeverityResult:
    """A scored triage decision, with its full justification.

    `contributions` and `triggered_rules` exist so the responder console can
    show *why* without re-running anything.
    """

    level: SeverityLevel
    score: float
    confidence: float
    #: Flag name to points added, for display and debugging.
    contributions: dict[str, float] = field(default_factory=dict)
    #: Names of hard rules that fired, e.g. "entanglement".
    triggered_rules: list[str] = field(default_factory=list)
    #: Plain-language reasons, one per hard rule or notable contribution.
    reasons: list[str] = field(default_factory=list)
    weather_adjustment: float = 0.0

    @property
    def level_number(self) -> int:
        """0-3, for comparison with the team's earlier research data."""
        return _LEVEL_ORDER.index(self.level)


def score_severity(
    injury: InjuryAssessment,
    hazards: SituationHazards,
    animal_group: AnimalGroup,
    context: EnvironmentalContext | None = None,
    *,
    data_quality_incomplete: bool = False,
    data_conflict: bool = False,
    needs_review: bool = False,
) -> SeverityResult:
    """Compute the triage level for one incident.

    Args:
        injury: The condition flags from the assessment agent.
        hazards: Threats from the surroundings (people, dogs, roads, surf).
        animal_group: Needed because some rules are group-specific -- a
            beached cetacean is critical in circumstances a seal would survive.
        context: Weather and tide. Omit it and the weather adjustment is zero.
        data_quality_incomplete: Intake ended without key answers.
        data_conflict: Vision and reporter disagreed materially.
        needs_review: An upstream check already asked for human eyes.

    Returns:
        A `SeverityResult`. Never raises -- missing inputs lower the
        confidence rather than failing, because a half-complete report of a
        dying animal still has to be triaged.
    """
    config = load_scoring_config()["severity"]
    flags = _collect_flags(injury, hazards)

    # --- Stage 1: hard rules ------------------------------------------------
    # These force CRITICAL. They exist because an additive score can dilute a
    # single decisive condition: an entangled animal with no other flags would
    # otherwise score 1.4 and be triaged as "monitor".
    triggered: list[str] = []
    reasons: list[str] = []

    for rule_name, rule in config["hard_rules"].items():
        required_group = rule.get("requires_animal_group")
        if required_group and animal_group.value != required_group:
            continue
        if all(flags.get(flag) for flag in rule["when"]):
            triggered.append(rule_name)
            reasons.append(rule["reason"])

    # --- Stage 2: additive weighted score -----------------------------------
    weights = config["scoring_weights"]
    contributions = {
        flag: weights[flag] for flag, is_set in flags.items() if is_set and flag in weights
    }
    condition_score = sum(contributions.values())

    # --- Stage 3: weather adjustment ----------------------------------------
    # Bad weather makes a borderline case more urgent, because the window for a
    # safe response is closing. It is capped so it can nudge but never dominate.
    weather_adjustment = 0.0
    if context is not None:
        adjustment_config = config["weather_adjustment"]
        raw = weather_risk_score(context.weather) * adjustment_config["multiplier"]
        weather_adjustment = min(raw, adjustment_config["max_points"])
        if weather_adjustment > 0:
            reasons.append(
                f"Conditions at the scene add {weather_adjustment:.2f} to urgency "
                "(a shorter safe window for responders)."
            )

    # A falling tide is a deadline, so it behaves like a hard urgency factor
    # for an animal that cannot move itself back to the water.
    tide_escalation = _tide_escalation(injury, animal_group, context)
    if tide_escalation:
        reasons.append(tide_escalation)

    total_score = condition_score + weather_adjustment

    # --- Stage 4: thresholds ------------------------------------------------
    thresholds = config["level_thresholds"]
    if triggered or total_score >= thresholds["critical"]:
        level = SeverityLevel.CRITICAL
    elif total_score >= thresholds["respond"]:
        level = SeverityLevel.RESPOND
    elif total_score >= thresholds["monitor"]:
        level = SeverityLevel.MONITOR
    else:
        level = SeverityLevel.GUIDANCE

    # Guard carried over from the prototype: weather alone must never be the
    # reason something is CRITICAL. Without this, a healthy animal on a stormy
    # day could be escalated to the top band on a 0.5-point nudge.
    if level is SeverityLevel.CRITICAL and not triggered:
        if condition_score < thresholds["critical"]:
            level = SeverityLevel.RESPOND
            reasons.append(
                "Held at RESPOND: the animal's condition alone does not reach "
                "critical, and weather is not sufficient grounds on its own."
            )

    # Tide escalation can raise MONITOR to RESPOND but, by the same logic,
    # never reaches CRITICAL by itself.
    if tide_escalation and level is SeverityLevel.MONITOR:
        level = SeverityLevel.RESPOND

    return SeverityResult(
        level=level,
        score=round(total_score, 2),
        confidence=_score_confidence(
            config["confidence"],
            animal_group=animal_group,
            incomplete=data_quality_incomplete,
            conflict=data_conflict,
            needs_review=needs_review,
        ),
        contributions=contributions,
        triggered_rules=triggered,
        reasons=reasons,
        weather_adjustment=round(weather_adjustment, 2),
    )


def _collect_flags(
    injury: InjuryAssessment, hazards: SituationHazards
) -> dict[str, bool]:
    """Flatten the two assessment objects into the flag names the weights use.

    Keeping this mapping in one place means `scoring_weights` keys in the JSON
    config line up with exactly one source field each.
    """
    return {
        "injury": injury.injury_present,
        "wound": injury.wound,
        "bleeding": injury.bleeding,
        "entanglement": injury.entanglement,
        "swelling": injury.swelling,
        "abnormal_posture": injury.abnormal_posture,
        "respiratory_distress": injury.respiratory_distress,
        "unresponsive": injury.unresponsive,
        # "Unknown" mobility is not a concern -- we only count a positive
        # finding, so an unanswered question cannot inflate severity.
        "mobility_concern": injury.mobility_concern
        in (MobilityConcern.LIMITED, MobilityConcern.IMMOBILE),
        "near_people": hazards.near_people,
        "near_dogs": hazards.near_dogs,
    }


def _tide_escalation(
    injury: InjuryAssessment,
    animal_group: AnimalGroup,
    context: EnvironmentalContext | None,
) -> str | None:
    """Explain any urgency added by the tide, or None.

    A falling tide plus an animal that cannot move itself is a hard deadline:
    every minute puts more distance between it and the water. This is the
    reasoning the prototype could not do, because it had no tide data at all.
    """
    if context is None or not context.is_coastal or context.tide is None:
        return None

    immobile = injury.mobility_concern in (MobilityConcern.LIMITED, MobilityConcern.IMMOBILE)
    if not immobile:
        return None

    if context.tide.trend == "falling":
        return (
            "Falling tide with an animal that cannot reach the water on its own: "
            "the distance to the sea is increasing and heat stress risk rises."
        )
    if context.tide.trend == "rising" and animal_group is AnimalGroup.CETACEAN:
        # Counter-intuitive but important: a rising tide can drown a beached
        # cetacean that cannot lift its blowhole clear of the water.
        return (
            "Rising tide with an immobile cetacean: risk of water covering the "
            "blowhole before the animal can refloat itself."
        )
    return None


def _score_confidence(
    config: dict,
    *,
    animal_group: AnimalGroup,
    incomplete: bool,
    conflict: bool,
    needs_review: bool,
) -> float:
    """How much to trust this severity score, from 0.45 to 0.92.

    Starts from a base and deducts for each known weakness in the inputs. The
    floor exists because even a poorly-sourced triage is better than none, and
    a score of 0.0 would read as "ignore this".
    """
    confidence = config["base"]
    if incomplete:
        confidence -= config["incomplete_penalty"]
    if needs_review:
        confidence -= config["review_needed_penalty"]
    if conflict:
        confidence -= config["data_conflict_penalty"]
    if animal_group is AnimalGroup.UNKNOWN:
        confidence -= config["unknown_species_penalty"]
    return round(max(confidence, config["minimum"]), 2)


def recommended_action(level: SeverityLevel) -> dict:
    """The action policy for a severity level, from `config/scoring.json`.

    Returns the dict with `recommended_action`, `alert_type`, `alert_priority`,
    `volunteer_allowed`, and `coordinator_review_required`.

    Note `volunteer_allowed`: at RESPOND and above, an untrained volunteer must
    not be sent. That is a safety boundary, not a preference.
    """
    actions = load_scoring_config()["recommended_actions"]
    return actions[str(_LEVEL_ORDER.index(level))]
