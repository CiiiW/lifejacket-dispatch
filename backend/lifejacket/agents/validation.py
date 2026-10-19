"""Agent 3: does the conclusion actually match the evidence?

Identification and assessment each look at the photo once and commit. Nothing
afterwards re-reads the picture to ask whether what was written down is what is
actually visible -- so a wound in plain sight paired with `wound: false` goes
all the way through to a responder, who drives out expecting a healthy animal.

This agent is given the photo *and* the conclusions drawn from it, and asked
one question: do these contradict each other? It looks for four kinds of
conflict:

1. **Photo vs. flags** -- a visible wound recorded as no wound; an obvious
   entanglement recorded as clear; an animal in the surf flagged as dry.
2. **Flags vs. flags** -- `bleeding: true` with `wound: false`;
   `mobility_concern: none` on an animal recorded as unresponsive.
3. **Species vs. scene** -- a species that does not occur on this coastline,
   or advice written for the wrong animal group.
4. **Conclusion vs. conditions** -- "tide will refloat it" when the tide is
   falling; "plenty of daylight" after sunset.

It is deliberately **not** the guardrail agent. The guardrail reads the
finished report and checks the *writing* for invented claims and unsafe
advice. This runs earlier, reads the *data*, and can still do something about
a problem: ask the reporter. By the time the guardrail sees a report, the
conversation is over.

Why a separate model call rather than more rules in `dispatch/`: a
contradiction between an image and a boolean is not expressible as a rule. The
flag-versus-flag cases could be, and some are already caught by severity
scoring, but the photo comparison needs a model that can see.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from lifejacket.agents.base import Agent
from lifejacket.llm.schema import (
    BOOLEAN,
    STRING,
    UNIT_INTERVAL,
    array_of,
    enum_of,
    object_schema,
)
from lifejacket.models.schemas import (
    AssessmentResult,
    ChatMessage,
    ClarifyingQuestion,
    IdentificationResult,
)


class Conflict(BaseModel):
    """One contradiction, and what it would take to settle it."""

    #: Which pair disagrees: "photo_vs_flags", "flags_vs_flags",
    #: "species_vs_scene", or "conclusion_vs_conditions".
    kind: str = ""
    #: What was recorded, e.g. "wound: false".
    recorded: str = ""
    #: What the evidence suggests instead, e.g. "a dark red open wound is
    #: visible on the animal's left flank".
    observed: str = ""
    #: How sure the checker is that this is a real conflict, not a judgement
    #: call. Low-confidence conflicts are reported but do not stop the flow.
    confidence: float = 0.0
    #: Which recorded field is in doubt, so a re-run knows what to revisit.
    field: str = ""


class ValidationResult(BaseModel):
    """The consistency check's findings."""

    #: True when at least one conflict was found, at any confidence.
    has_conflict: bool = False
    conflicts: list[Conflict] = Field(default_factory=list)
    #: What to ask the reporter to resolve the most serious conflict. Empty
    #: when nothing a reporter could answer would settle it -- a disagreement
    #: about species range, for instance, is not theirs to resolve.
    next_question: ClarifyingQuestion | None = None
    #: One line for the responder console, whether or not anything is wrong.
    notes: str | None = None

    @property
    def blocking_conflicts(self) -> list[Conflict]:
        """Conflicts solid enough to be worth another question.

        A 0.4-confidence hunch that a shadow might be a wound is worth
        recording and not worth interrupting someone on a beach for.
        """
        return [c for c in self.conflicts if c.confidence >= 0.6]


_CONFLICT = object_schema(
    {
        "kind": enum_of(
            "photo_vs_flags",
            "flags_vs_flags",
            "species_vs_scene",
            "conclusion_vs_conditions",
        ),
        "recorded": STRING,
        "observed": STRING,
        "confidence": UNIT_INTERVAL,
        "field": STRING,
    }
)

_SCHEMA = object_schema(
    {
        "has_conflict": BOOLEAN,
        # Capped: beyond a few, the model starts listing stylistic quibbles
        # rather than contradictions.
        "conflicts": array_of(_CONFLICT, max_items=4),
        "next_question": STRING,
        "next_question_rationale": STRING,
        "next_question_options": {"type": "array", "items": STRING},
        "next_question_feature": STRING,
        "notes": STRING,
    }
)


class ValidationAgent(Agent[ValidationResult]):
    """Checks the identification and assessment against the photo and context."""

    name = "validation"
    prompt_path = "validation/check_consistency.md"
    result_type = ValidationResult
    # Zero temperature: a consistency check should reach the same verdict on
    # the same evidence every time, like the guardrail.
    temperature = 0.0

    @property
    def output_schema(self) -> dict[str, Any]:
        return _SCHEMA

    def build_prompt_values(
        self,
        *,
        identification: IdentificationResult | None = None,
        assessment: AssessmentResult | None = None,
        environment_summary: str = "No environmental data available.",
        identification_summary: str = "Not recorded.",
        photo_count: int = 1,
        transcript: list[ChatMessage] | None = None,
        target_context: str = "Analyse the animal in the active photo.",
    ) -> dict[str, Any]:
        return {
            "photo_count": photo_count,
            "target_context": target_context,
            "species": identification.display_name if identification else "unidentified",
            "species_confidence": (
                f"{identification.confidence:.2f}" if identification else "unknown"
            ),
            "animal_group": (
                identification.animal_group.value if identification else "unknown"
            ),
            "identification_summary": identification_summary,
            "recorded_flags": _render_flags(assessment),
            "environment_summary": environment_summary,
            "transcript": _format_transcript(transcript or []),
        }

    def parse(self, data: dict[str, Any]) -> ValidationResult:
        """Rebuild the nested question from the flattened JSON fields."""
        conflicts = [
            Conflict(
                kind=(c.get("kind") or "").strip(),
                recorded=(c.get("recorded") or "").strip(),
                observed=(c.get("observed") or "").strip(),
                confidence=c.get("confidence", 0.0),
                field=(c.get("field") or "").strip(),
            )
            for c in data.get("conflicts", [])
            if c.get("recorded") or c.get("observed")
        ]

        question_text = (data.get("next_question") or "").strip()
        next_question = None
        if question_text:
            next_question = ClarifyingQuestion(
                question=question_text,
                rationale=(data.get("next_question_rationale") or "").strip() or None,
                options=[o for o in data.get("next_question_options", []) if o],
                feature=(data.get("next_question_feature") or "").strip() or None,
            )

        return ValidationResult(
            # Trust the list over the boolean: a model that lists three
            # contradictions and then says has_conflict=false has contradicted
            # itself, which is the one thing this agent exists to notice.
            has_conflict=bool(data.get("has_conflict")) or bool(conflicts),
            conflicts=conflicts,
            next_question=next_question,
            notes=(data.get("notes") or "").strip() or None,
        )


def _format_transcript(messages: list[ChatMessage]) -> str:
    """Render the conversation so the checker can see what was asked."""
    if not messages:
        return "(No questions asked yet.)"
    return "\n".join(f"{m.role.value.upper()}: {m.content}" for m in messages)


def _render_flags(assessment: AssessmentResult | None) -> str:
    """The recorded conclusions, written out for the checker to compare."""
    if assessment is None:
        return "(No assessment recorded yet.)"

    injury = assessment.injury
    hazards = assessment.hazards
    return "\n".join(
        [
            "CONDITION, as recorded by the assessment agent:",
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
            "SURROUNDINGS, as recorded:",
            f"  near_people: {hazards.near_people}",
            f"  near_dogs: {hazards.near_dogs}",
            f"  near_road: {hazards.near_road}",
            f"  in_surf: {hazards.in_surf}",
            f"  risk_of_being_stranded_further: {hazards.risk_of_being_stranded_further}",
            f"  notes: {hazards.notes or '(none)'}",
            "",
            "CONCLUSIONS, as recorded:",
            f"  recommended_action: {assessment.recommended_action or '(none)'}",
            f"  environmental_rationale: {assessment.environmental_rationale or '(none)'}",
        ]
    )
