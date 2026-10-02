"""Agent 1: identify the animal from photos plus a short conversation.

The job is to get from "here is a photo of something on a beach" to a genus
and species confident enough to route on -- asking **at most five questions**.

Two things make this harder than ordinary image classification:

- **Confusable species.** A harbour porpoise and a common dolphin look alike in
  a phone photo, as do several seal species. The research in
  `research/vision_confidence/` found the model reached only ~54% top-1
  accuracy on its best prompt, and crucially, **50 of 485 answers given at 90%+
  confidence were wrong**. Vision alone is not enough.
- **The reporter is standing on a beach.** Questions must be answerable from a
  safe distance, without touching or approaching the animal, by someone with no
  training. "Does it have visible ear flaps?" works. "Is the dentition
  homodont?" does not.

So the agent asks questions that discriminate between its *current top
candidates*, rather than running through a fixed checklist. Each question
targets the single feature that best separates the leading hypotheses.
"""

from __future__ import annotations

from typing import Any

from lifejacket.agents.base import Agent
from lifejacket.config import settings
from lifejacket.llm.schema import (
    BOOLEAN,
    SPECIES_CANDIDATE,
    STRING,
    array_of,
    object_schema,
)
from lifejacket.models.schemas import (
    AnimalGroup,
    ChatMessage,
    ClarifyingQuestion,
    IdentificationResult,
    SpeciesCandidate,
)
from lifejacket.taxonomy import resolve_taxon

#: Shape of the identification reply.
_SCHEMA = object_schema(
    {
        # Capped at four: beyond that the model pads the list with near-zero
        # guesses that add no information and dilute the top candidate.
        "candidates": array_of(SPECIES_CANDIDATE, max_items=4),
        # No "is_confident" field: the system works confidence out itself by
        # pooling these probabilities up the taxonomy (see taxonomy.py).
        "species_distinguishable": BOOLEAN,
        "reasoning": STRING,
        "needs_new_photo": BOOLEAN,
        "photo_quality_note": STRING,
        # Flattened rather than nested, because a nested optional object is the
        # field models most often return as null-shaped garbage.
        "next_question": STRING,
        "next_question_rationale": STRING,
        "next_question_options": {"type": "array", "items": STRING},
        "next_question_feature": STRING,
    }
)


class IdentificationAgent(Agent[IdentificationResult]):
    """Identifies genus/species from photos and reporter answers."""

    name = "identification"
    prompt_path = "identification/identify_species.md"
    result_type = IdentificationResult
    # Low temperature: identification should be reproducible so that the
    # evaluation harness measures the prompt, not sampling noise.
    temperature = 0.1

    @property
    def output_schema(self) -> dict[str, Any]:
        return _SCHEMA

    def build_prompt_values(
        self,
        *,
        location_summary: str = "Location unavailable.",
        transcript: list[ChatMessage] | None = None,
        questions_asked: int = 0,
        questions_remaining: int = 5,
        previous_candidates: list[SpeciesCandidate] | None = None,
        photo_count: int = 1,
    ) -> dict[str, Any]:
        return {
            "location_summary": location_summary,
            "photo_count": photo_count,
            "questions_asked": questions_asked,
            "questions_remaining": questions_remaining,
            "transcript": _format_transcript(transcript or []),
            "previous_candidates": _format_candidates(previous_candidates or []),
            "features_already_probed": _format_probed_features(transcript or []),
        }

    def parse(self, data: dict[str, Any]) -> IdentificationResult:
        """Rebuild the nested question object from the flattened JSON fields."""
        candidates = [
            SpeciesCandidate(
                common_name=c.get("common_name", ""),
                scientific_name=c.get("scientific_name") or None,
                confidence=c.get("confidence", 0.0),
                animal_group=_safe_group(c.get("animal_group")),
                genus=c.get("genus") or None,
                genus_common_name=c.get("genus_common_name") or None,
                family=c.get("family") or None,
                family_common_name=c.get("family_common_name") or None,
            )
            for c in data.get("candidates", [])
            if c.get("common_name")
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

        return IdentificationResult(
            candidates=candidates,
            # The model supplies probabilities; Python decides the rank.
            resolution=resolve_taxon(
                candidates, settings.identification_confidence_threshold
            ),
            species_distinguishable=bool(data.get("species_distinguishable", True)),
            next_question=next_question,
            needs_new_photo=bool(data.get("needs_new_photo")),
            photo_quality_note=(data.get("photo_quality_note") or "").strip() or None,
            reasoning=(data.get("reasoning") or "").strip() or None,
        )


def _safe_group(value: str | None) -> AnimalGroup:
    """Coerce the model's group string, defaulting to UNKNOWN.

    The schema has an enum so this should always succeed, but a wrong group is
    worse than an unknown one -- it routes the incident to the wrong
    specialists -- so the failure mode is explicit.
    """
    try:
        return AnimalGroup(value) if value else AnimalGroup.UNKNOWN
    except ValueError:
        return AnimalGroup.UNKNOWN


def _format_transcript(messages: list[ChatMessage]) -> str:
    """Render the conversation so far for inclusion in the prompt."""
    if not messages:
        return "(No questions asked yet.)"
    return "\n".join(f"{m.role.value.upper()}: {m.content}" for m in messages)


def _format_candidates(candidates: list[SpeciesCandidate]) -> str:
    """Render the previous round's hypotheses.

    Shown so the model can revise its own earlier estimate in light of a new
    answer, rather than starting from scratch each turn and oscillating.
    """
    if not candidates:
        return "(No previous assessment -- this is the first look at the photo.)"
    return "\n".join(
        f"- {c.common_name}"
        + (f" ({c.scientific_name})" if c.scientific_name else "")
        + (f", family {c.family}" if c.family else "")
        + f": {c.confidence:.2f}"
        for c in candidates
    )


def _format_probed_features(messages: list[ChatMessage]) -> str:
    """List features already asked about.

    Without this the agent re-asks the same discriminating question in
    different words, burning the five-question budget. The prototype hit this
    and worked around it by string-matching exact repeats, which failed as soon
    as the phrasing changed.
    """
    features = [m.feature for m in messages if m.feature]
    if not features:
        return "(None yet.)"
    return ", ".join(dict.fromkeys(features))
