"""Agent 3: distil everything into the report that goes out to responders.

The audience is specific and it is not the reporter. It is a stranding-network
coordinator or a trained volunteer, reading a push notification while finding
their car keys. They need to know, in order: what animal, where, how bad, what
to bring, what to watch out for.

Three constraints shape the output:

- **The headline must stand alone.** It is all many recipients will read before
  deciding whether to act, so it carries species, place, and the single most
  urgent fact.
- **Unknowns are stated, not omitted.** "Tide state unknown" is useful;
  silence about the tide reads as "nothing unusual", which is a different and
  false claim.
- **Nothing may be invented.** Every statement has to trace back to the
  assessment, the conversation, or the environmental data. The guardrail agent
  in `agents/guardrail.py` checks this afterwards.
"""

from __future__ import annotations

from typing import Any

from lifejacket.agents.base import Agent
from lifejacket.llm.schema import STRING, STRING_LIST, object_schema
from lifejacket.models.schemas import (
    AssessmentResult,
    ChatMessage,
    EnvironmentalContext,
    IdentificationResult,
    IncidentReport,
    SeverityLevel,
)
from lifejacket.taxonomy import describe_resolution

_SCHEMA = object_schema(
    {
        "headline": STRING,
        "summary": STRING,
        "recommended_actions": STRING_LIST,
        "access_notes": STRING,
        "equipment_suggestions": STRING_LIST,
        "hazard_warnings": STRING_LIST,
        "unknowns": STRING_LIST,
        "reporter_contact_note": STRING,
    }
)


class ReportAgent(Agent[IncidentReport]):
    """Writes the responder-facing incident report."""

    name = "report"
    prompt_path = "report/write_report.md"
    result_type = IncidentReport
    # Slightly higher than the classification agents: this output is prose that
    # a human reads under pressure, and it needs to be fluent.
    temperature = 0.3

    @property
    def output_schema(self) -> dict[str, Any]:
        return _SCHEMA

    def build_prompt_values(
        self,
        *,
        identification: IdentificationResult,
        assessment: AssessmentResult,
        context: EnvironmentalContext | None = None,
        environment_summary: str = "No environmental data available.",
        transcript: list[ChatMessage] | None = None,
        severity_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        resolution = identification.resolution

        return {
            "species": identification.display_name,
            "scientific_name": (resolution.scientific_name if resolution else None)
            or "not established",
            "species_confidence": f"{identification.confidence:.2f}",
            "identification_summary": describe_resolution(resolution),
            "animal_group": identification.animal_group.value,
            "place_name": (
                context.location.place_name if context and context.location else None
            )
            or "location name unresolved",
            "coordinates": (
                f"{context.location.latitude:.5f}, {context.location.longitude:.5f}"
                if context and context.location
                else "unknown"
            ),
            "severity_level": assessment.severity_level.value,
            "severity_score": f"{assessment.severity_score:.2f}",
            "severity_reasons": _bullet_list(severity_reasons or []),
            "condition_flags": _format_flags(assessment),
            "recommended_action": assessment.recommended_action or "not determined",
            "time_sensitivity": (
                f"{assessment.time_sensitivity_hours:.1f} hours"
                if assessment.time_sensitivity_hours is not None
                else "not established"
            ),
            "environment_summary": environment_summary,
            "transcript": _format_transcript(transcript or []),
            "known_gaps": _bullet_list(
                (context.unavailable if context else []) + _assessment_gaps(assessment)
            ),
            "volunteer_allowed": (
                "no -- professional team required"
                if assessment.severity_level
                in (SeverityLevel.CRITICAL, SeverityLevel.RESPOND)
                else "yes -- a trained volunteer may attend"
            ),
        }


def _format_flags(assessment: AssessmentResult) -> str:
    """List only the condition flags that are set.

    Positives only: a wall of `false` values buries the two that matter.
    """
    injury = assessment.injury
    flags = {
        "wound": injury.wound,
        "bleeding": injury.bleeding,
        "entanglement": injury.entanglement,
        "swelling": injury.swelling,
        "abnormal posture": injury.abnormal_posture,
        "respiratory distress": injury.respiratory_distress,
        "unresponsive": injury.unresponsive,
        "emaciated": injury.emaciated,
        "near people": assessment.hazards.near_people,
        "near dogs": assessment.hazards.near_dogs,
        "near road": assessment.hazards.near_road,
        "in surf": assessment.hazards.in_surf,
    }
    present = [name for name, is_set in flags.items() if is_set]

    lines = [f"- {name}" for name in present] or ["- (no positive condition flags)"]
    lines.append(f"- mobility: {injury.mobility_concern.value}")
    if injury.summary:
        lines.append(f"- summary: {injury.summary}")
    return "\n".join(lines)


def _assessment_gaps(assessment: AssessmentResult) -> list[str]:
    """Known weaknesses in the assessment, to be surfaced as explicit unknowns."""
    gaps: list[str] = []
    if assessment.injury.mobility_concern.value == "unknown":
        gaps.append("whether the animal can move was never established")
    if not assessment.is_confident:
        gaps.append("the assessment ended without full confidence")
    if assessment.severity_confidence and assessment.severity_confidence < 0.6:
        gaps.append(
            f"triage confidence is low ({assessment.severity_confidence:.2f}) "
            "because of incomplete intake"
        )
    return gaps


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def _format_transcript(messages: list[ChatMessage]) -> str:
    if not messages:
        return "(No conversation recorded.)"
    return "\n".join(f"{m.role.value.upper()}: {m.content}" for m in messages)
