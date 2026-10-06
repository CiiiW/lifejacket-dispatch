"""Agent 2: work out what is wrong with the animal and what should happen.

Runs once the species is settled. It combines the identification, the photos,
the reporter's answers, and the environmental context (tide, weather, daylight)
into a structured condition assessment.

**What this agent decides and what it does not.** It decides *observations*:
is there a wound, is the animal entangled, can it move, is it near a road. It
writes the reporter-facing guidance and the environmental reasoning.

It does **not** decide the severity level. That is computed from its
observations by `dispatch.severity.score_severity`, which is deterministic and
auditable. The agent's observations are the input to triage, not the triage
itself.

This split is the main correction to the prototype, where an LLM prompt
assigned severity 0-3 directly while a separate deterministic path computed a
different number from the same flags -- and the prompt was explicitly told to
ignore weather, which the new specification requires.
"""

from __future__ import annotations

from typing import Any

from lifejacket.agents.base import Agent
from lifejacket.llm.schema import (
    BOOLEAN,
    INTEGER,
    NUMBER,
    STRING,
    STRING_LIST,
    UNIT_INTERVAL,
    enum_of,
    object_schema,
)
from lifejacket.models.schemas import (
    AnimalGroup,
    AssessmentResult,
    ChatMessage,
    ClarifyingQuestion,
    EnvironmentalContext,
    IdentificationResult,
    InjuryAssessment,
    MobilityConcern,
    SituationHazards,
)
from lifejacket.taxonomy import describe_resolution

_SCHEMA = object_schema(
    {
        # --- Condition flags. Every one required: see llm/schema.py on why a
        # forced `false` beats a silent omission. ---
        "injury_present": BOOLEAN,
        "injury_confidence": UNIT_INTERVAL,
        "wound": BOOLEAN,
        "bleeding": BOOLEAN,
        "entanglement": BOOLEAN,
        "swelling": BOOLEAN,
        "abnormal_posture": BOOLEAN,
        "respiratory_distress": BOOLEAN,
        "unresponsive": BOOLEAN,
        "emaciated": BOOLEAN,
        "mobility_concern": enum_of("none", "limited", "immobile", "unknown"),
        "injury_summary": STRING,
        # --- Surroundings ---
        "near_people": BOOLEAN,
        "near_dogs": BOOLEAN,
        "near_road": BOOLEAN,
        "in_surf": BOOLEAN,
        "risk_of_being_stranded_further": BOOLEAN,
        "hazard_notes": STRING,
        # --- Scale: one animal or several. Feeds mass-stranding detection. ---
        "animal_count": {**INTEGER, "minimum": 1},
        # --- Guidance ---
        "recommended_action": STRING,
        "reporter_instructions": STRING_LIST,
        "safety_guidance": STRING,
        "environmental_rationale": STRING,
        "time_sensitivity_hours": NUMBER,
        # --- Conversation control ---
        "is_confident": BOOLEAN,
        "next_question": STRING,
        "next_question_rationale": STRING,
        "next_question_options": {"type": "array", "items": STRING},
        "next_question_feature": STRING,
    }
)


class AssessmentAgent(Agent[AssessmentResult]):
    """Assesses condition and situation, and writes reporter guidance."""

    name = "assessment"
    prompt_path = "assessment/assess_situation.md"
    result_type = AssessmentResult
    temperature = 0.2

    @property
    def output_schema(self) -> dict[str, Any]:
        return _SCHEMA

    def build_prompt_values(
        self,
        *,
        identification: IdentificationResult | None = None,
        context: EnvironmentalContext | None = None,
        environment_summary: str = "No environmental data available.",
        transcript: list[ChatMessage] | None = None,
        questions_asked: int = 0,
        questions_remaining: int = 5,
    ) -> dict[str, Any]:
        group = identification.animal_group if identification else AnimalGroup.UNKNOWN
        resolution = identification.resolution if identification else None

        return {
            "species": (
                identification.display_name if identification else "unidentified animal"
            ),
            "scientific_name": (
                (resolution.scientific_name if resolution else None) or "unknown"
            ),
            "species_confidence": f"{identification.confidence:.2f}"
            if identification
            else "0.00",
            # Says what rank the identification reached and lists the species
            # probabilities, e.g. "oceanic dolphins ... common 0.48, bottlenose 0.41".
            "identification_summary": describe_resolution(resolution),
            "animal_group": group.value,
            "group_specific_notes": _group_notes(group),
            "environment_summary": environment_summary,
            "transcript": _format_transcript(transcript or []),
            "questions_asked": questions_asked,
            "questions_remaining": questions_remaining,
            "is_coastal": "yes" if (context and context.is_coastal) else "no/unknown",
        }

    def parse(self, data: dict[str, Any]) -> AssessmentResult:
        """Build the result. Severity is left at its default and filled in later.

        `services.pipeline` calls `dispatch.severity.score_severity` on the
        flags below and writes the real level in. Nothing downstream should read
        severity off this object before that happens.
        """
        injury = InjuryAssessment(
            injury_present=bool(data.get("injury_present")),
            confidence=data.get("injury_confidence", 0.0),
            wound=bool(data.get("wound")),
            bleeding=bool(data.get("bleeding")),
            entanglement=bool(data.get("entanglement")),
            swelling=bool(data.get("swelling")),
            abnormal_posture=bool(data.get("abnormal_posture")),
            respiratory_distress=bool(data.get("respiratory_distress")),
            unresponsive=bool(data.get("unresponsive")),
            emaciated=bool(data.get("emaciated")),
            mobility_concern=_safe_mobility(data.get("mobility_concern")),
            summary=(data.get("injury_summary") or "").strip() or None,
        )

        hazards = SituationHazards(
            near_people=bool(data.get("near_people")),
            near_dogs=bool(data.get("near_dogs")),
            near_road=bool(data.get("near_road")),
            in_surf=bool(data.get("in_surf")),
            risk_of_being_stranded_further=bool(data.get("risk_of_being_stranded_further")),
            notes=(data.get("hazard_notes") or "").strip() or None,
        )

        question_text = (data.get("next_question") or "").strip()
        next_question = None
        if question_text:
            next_question = ClarifyingQuestion(
                question=question_text,
                rationale=(data.get("next_question_rationale") or "").strip() or None,
                options=[o for o in data.get("next_question_options", []) if o],
                feature=(data.get("next_question_feature") or "").strip() or None,
            )

        return AssessmentResult(
            animal_count=_safe_count(data.get("animal_count")),
            injury=injury,
            hazards=hazards,
            recommended_action=(data.get("recommended_action") or "").strip(),
            reporter_instructions=[i for i in data.get("reporter_instructions", []) if i],
            safety_guidance=(data.get("safety_guidance") or "").strip(),
            environmental_rationale=(
                data.get("environmental_rationale") or ""
            ).strip()
            or None,
            time_sensitivity_hours=data.get("time_sensitivity_hours"),
            is_confident=bool(data.get("is_confident")),
            next_question=next_question,
        )


def _safe_count(value: Any) -> int:
    """How many animals, defaulting to one.

    A missing, zero, or nonsense count means "one": there is a report, so
    there is at least one animal, and anything above one has to be claimed
    rather than assumed. A bool is rejected because `True` is an int in Python.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1
    return max(1, int(value))


def _safe_mobility(value: str | None) -> MobilityConcern:
    try:
        return MobilityConcern(value) if value else MobilityConcern.UNKNOWN
    except ValueError:
        return MobilityConcern.UNKNOWN


def _group_notes(group: AnimalGroup) -> str:
    """Group-specific biology the model must weigh.

    Injected rather than left to the model's general knowledge because these
    facts change the recommendation completely, and a general-purpose model
    will not reliably surface them unprompted. A beached dolphin and a resting
    seal look similarly inert in a photo but need opposite advice.
    """
    notes = {
        AnimalGroup.PINNIPED: (
            "Seals and sea lions rest on land normally. Hauling out is NOT by itself "
            "a sign of distress, and healthy pups are often left alone by a foraging "
            "mother for a day or more. Moving a healthy pup orphans it. Look for "
            "actual injury, severe emaciation, entanglement, or a pup clearly too "
            "young to be weaned."
        ),
        AnimalGroup.CETACEAN: (
            "A whale, dolphin, or porpoise out of the water is ALWAYS a critical "
            "emergency. Their body weight crushes their lungs and they overheat "
            "rapidly without water to cool them. Never let anyone push a stranded "
            "cetacean back to sea -- it usually restrands, and it may be beaching "
            "because it is sick. The blowhole must stay clear of water at all times."
        ),
        AnimalGroup.SEA_TURTLE: (
            "A sea turtle on a beach outside nesting season is likely cold-stunned, "
            "injured, or ill. Cold-stunned turtles appear dead but often are not -- "
            "they must never be put back in the water, and must not be rapidly "
            "warmed. Keep dry, shaded, and still."
        ),
        AnimalGroup.SEABIRD: (
            "Check for oiling, fishing line, and hooks. An oiled bird must not be "
            "cleaned by the public: amateur washing removes waterproofing and kills "
            "birds that would otherwise be saveable."
        ),
        AnimalGroup.OTHER_MARINE: (
            "A marine animal outside the usual pinniped/cetacean/turtle groups -- "
            "for example a sea otter, manatee, large fish, or jellyfish. Cold "
            "water species lose body heat fast once stranded; keep them damp and "
            "shaded rather than dry. Treat any bite or sting risk (rays, jellyfish, "
            "eels) as a reason to keep the reporter further back, not closer."
        ),
        AnimalGroup.TERRESTRIAL: (
            "A wild land animal -- deer, raccoon, coyote, bird of prey, snake, and "
            "so on. This is a genuine report, just outside the marine stranding "
            "network this system currently dispatches through (see "
            "`data/rescue_centers.csv`), so no specialised responder will be "
            "suggested yet. Give safety-first advice: keep well back, keep dogs "
            "and children away, never attempt to handle or corner it (bites and "
            "rabies-vector species are a real risk), and tell the reporter to "
            "contact their local wildlife rehabilitator or animal control "
            "directly rather than wait for this system to dispatch someone."
        ),
        AnimalGroup.DOMESTIC_ANIMAL: (
            "A pet or livestock animal (dog, cat, horse, chicken, ...), not "
            "wildlife. This is almost always a false report for a wildlife-rescue "
            "system -- say so plainly, and direct the reporter to animal control, "
            "a humane society, or the owner rather than a wildlife responder."
        ),
    }
    return notes.get(
        group,
        "Animal group could not be determined. Give conservative, general "
        "advice: keep distance, do not touch, do not move the animal, and "
        "prioritise getting a trained responder to identify it on scene.",
    )


def _format_transcript(messages: list[ChatMessage]) -> str:
    if not messages:
        return "(No conversation yet.)"
    return "\n".join(f"{m.role.value.upper()}: {m.content}" for m in messages)
