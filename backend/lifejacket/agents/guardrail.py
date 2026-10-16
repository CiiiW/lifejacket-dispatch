"""The guardrail agent: a second model checks the report before anyone sees it.

This pattern is carried forward from the team's prototype, where it was the
strongest idea in the codebase. A separate model call, with no stake in the
original answer, reviews the generated report against the underlying data and
answers two questions:

1. **Is it grounded?** Does every claim trace back to the assessment, the
   conversation, or the environmental data? A report that invents "the animal
   has been there since yesterday" sends a team out on a false premise.
2. **Is it safe?** Does it tell anyone to do something that would hurt them or
   the animal? The dangerous advice here is specific and recurring: pushing a
   stranded cetacean back to sea, pouring water into a blowhole, moving an
   apparently-orphaned seal pup, members of the public cleaning an oiled bird.

A report that fails either check is **held for human review** rather than
discarded. The coordinator sees the report, the violations, and the reason --
and decides. Blocking outright would mean a guardrail false positive could
suppress a real emergency.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from lifejacket.agents.base import Agent
from lifejacket.llm.schema import BOOLEAN, STRING, STRING_LIST, object_schema
from lifejacket.models.schemas import AssessmentResult, IncidentReport


class GuardrailVerdict(BaseModel):
    """The reviewer's findings."""

    is_grounded: bool = True
    is_safe: bool = True
    #: Claims in the report with no support in the source data.
    unsupported_claims: list[str] = Field(default_factory=list)
    #: Advice that could endanger a person or the animal.
    unsafe_advice: list[str] = Field(default_factory=list)
    #: Things a responder needs that the report omitted.
    missing_critical_content: list[str] = Field(default_factory=list)
    notes: str | None = None
    #: True when the check itself could not run (model failure), as opposed to
    #: running and finding a problem. Set by the pipeline, never by the model.
    check_failed: bool = False

    @property
    def approved(self) -> bool:
        """Whether the report can be released without a human reading it first."""
        return self.is_grounded and self.is_safe


_SCHEMA = object_schema(
    {
        "is_grounded": BOOLEAN,
        "is_safe": BOOLEAN,
        "unsupported_claims": STRING_LIST,
        "unsafe_advice": STRING_LIST,
        "missing_critical_content": STRING_LIST,
        "notes": STRING,
    }
)


class GuardrailAgent(Agent[GuardrailVerdict]):
    """Reviews a generated report for groundedness and safety."""

    name = "guardrail"
    prompt_path = "report/guardrail_review.md"
    result_type = GuardrailVerdict
    # Zero temperature: this is a check, and it should give the same verdict on
    # the same input every time.
    temperature = 0.0

    @property
    def output_schema(self) -> dict[str, Any]:
        return _SCHEMA

    def build_prompt_values(
        self,
        *,
        report: IncidentReport,
        assessment: AssessmentResult,
        environment_summary: str = "No environmental data available.",
        species: str = "unidentified animal",
        identification_summary: str = "Not recorded.",
    ) -> dict[str, Any]:
        return {
            "species": species,
            "report_text": _render_report(report),
            "source_data": _render_source(
                assessment, environment_summary, identification_summary
            ),
        }


def _render_report(report: IncidentReport) -> str:
    """Flatten the report into the text the reviewer reads."""
    sections = [
        f"HEADLINE: {report.headline}",
        f"SUMMARY: {report.summary}",
        "RECOMMENDED ACTIONS:\n"
        + "\n".join(f"  - {a}" for a in report.recommended_actions or ["(none)"]),
    ]
    if report.access_notes:
        sections.append(f"ACCESS NOTES: {report.access_notes}")
    if report.equipment_suggestions:
        sections.append(
            "EQUIPMENT:\n" + "\n".join(f"  - {e}" for e in report.equipment_suggestions)
        )
    if report.hazard_warnings:
        sections.append(
            "HAZARDS:\n" + "\n".join(f"  - {h}" for h in report.hazard_warnings)
        )
    if report.unknowns:
        sections.append("UNKNOWNS:\n" + "\n".join(f"  - {u}" for u in report.unknowns))
    return "\n\n".join(sections)


def _render_source(
    assessment: AssessmentResult, environment_summary: str, identification_summary: str
) -> str:
    """The ground truth the report is checked against.

    Only what the pipeline actually established goes in here. If a fact is not
    in this block, the report is not entitled to assert it.
    """
    injury = assessment.injury
    hazards = assessment.hazards

    return "\n".join(
        [
            "IDENTIFICATION (authoritative, including species probabilities):",
            f"  {identification_summary}",
            "",
            "ANIMAL COUNT (authoritative):",
            f"  animals in trouble: {assessment.animal_count}",
            "",
            "CONDITION FLAGS (authoritative):",
            f"  injury_present: {injury.injury_present}",
            f"  wound: {injury.wound}",
            f"  bleeding: {injury.bleeding}",
            f"  entanglement: {injury.entanglement}",
            f"  swelling: {injury.swelling}",
            f"  abnormal_posture: {injury.abnormal_posture}",
            f"  respiratory_distress: {injury.respiratory_distress}",
            f"  unresponsive: {injury.unresponsive}",
            f"  emaciated: {injury.emaciated}",
            f"  mobility_concern: {injury.mobility_concern.value}",
            f"  injury_summary: {injury.summary or '(none)'}",
            "",
            "SITUATION FLAGS (authoritative):",
            f"  near_people: {hazards.near_people}",
            f"  near_dogs: {hazards.near_dogs}",
            f"  near_road: {hazards.near_road}",
            f"  in_surf: {hazards.in_surf}",
            f"  risk_of_being_stranded_further: {hazards.risk_of_being_stranded_further}",
            f"  notes: {hazards.notes or '(none)'}",
            "",
            "TRIAGE (authoritative, computed deterministically):",
            f"  severity_level: {assessment.severity_level.value}",
            f"  severity_score: {assessment.severity_score}",
            f"  severity_confidence: {assessment.severity_confidence}",
            f"  recommended_action: {assessment.recommended_action}",
            "",
            "ENVIRONMENT (authoritative):",
            environment_summary,
        ]
    )
