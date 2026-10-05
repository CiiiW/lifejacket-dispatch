"""An offline stand-in for the real model, for tests and credential-free demos.

`ScriptedLLMClient` has the same `generate_json` method as `LLMClient`, so any
agent accepts it. Instead of calling Gemini it replies from a queue of canned
JSON responses, one queue per agent.

What it is for:

- **Tests** of the full pipeline -- question budgets, taxon resolution,
  severity, report, guardrail -- with no network and no API key.
- **Exploring the conversation flow** in the notebooks before you have GCP
  access. The prompts are still rendered for real, so you can read exactly
  what Gemini *would* have been sent (`client.calls`).

What it is NOT for: judging answer quality. The replies are written by hand.
Use the real client (`LLMClient()`) for that.

Failures can be scripted too, to test what the pipeline does when the model is
down. Queue an exception instead of a reply and it is raised on that call:

    client.queue("identification", LLMCallError("Vertex unavailable", attempts=3))

Three built-in scenarios cover the three ways identification can stop:

    ScriptedLLMClient.scenario("sea_lion")  # confident species, zero questions
    ScriptedLLMClient.scenario("seal")      # one question settles the species
    ScriptedLLMClient.scenario("dolphin")   # species inseparable -> family level
"""

from __future__ import annotations

import copy
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from lifejacket.llm.client import ImageInput, LLMResponse

logger = logging.getLogger(__name__)


@dataclass
class RecordedCall:
    """One request the scripted client received."""

    agent: str
    prompt: str
    image_count: int


@dataclass
class ScriptedLLMClient:
    """Replies to each agent from its own queue of canned responses.

    When an agent's queue runs out, the last response is repeated (with a
    warning) so a notebook session does not crash because you answered one
    question more than the script anticipated.
    """

    script: dict[str, list[dict[str, Any] | Exception]] = field(default_factory=dict)
    model: str = "scripted-offline"
    max_retries: int = 1
    #: Every request received, so a notebook can print the rendered prompts.
    calls: list[RecordedCall] = field(default_factory=list)
    _served: dict[str, int] = field(
        default_factory=lambda: defaultdict(int), init=False, repr=False
    )

    def queue(
        self, agent: str, *responses: dict[str, Any] | Exception
    ) -> ScriptedLLMClient:
        """Append replies for an agent: identification, assessment, report, guardrail.

        An exception in the queue is raised instead of returned, which is how
        tests simulate the model being unavailable for one call.
        """
        self.script.setdefault(agent, []).extend(responses)
        return self

    def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        images: list[ImageInput] | None = None,
        temperature: float | None = None,
        system_instruction: str | None = None,
    ) -> LLMResponse:
        agent = agent_for_schema(schema)
        self.calls.append(RecordedCall(agent, prompt, len(images or [])))

        replies = self.script.get(agent)
        if not replies:
            raise RuntimeError(
                f"ScriptedLLMClient has no replies queued for the '{agent}' agent. "
                f"Use .queue('{agent}', {{...}}) or a built-in scenario."
            )

        index = self._served[agent]
        if index >= len(replies):
            logger.warning(
                "Scripted '%s' replies exhausted after %d; repeating the last one.",
                agent,
                len(replies),
            )
            index = len(replies) - 1
        self._served[agent] += 1

        reply = replies[index]
        if isinstance(reply, Exception):
            raise reply

        data = copy.deepcopy(reply)
        return LLMResponse(
            data=data, raw_text=str(data), model=self.model, latency_seconds=0.0
        )

    @classmethod
    def scenario(cls, name: str) -> ScriptedLLMClient:
        """A ready-made conversation. See `SCENARIOS` for what each one does."""
        if name not in SCENARIOS:
            raise KeyError(f"Unknown scenario '{name}'. Choose from: {', '.join(SCENARIOS)}")
        return cls(script=copy.deepcopy(SCENARIOS[name]))


def agent_for_schema(schema: dict[str, Any]) -> str:
    """Work out which agent is calling from a field unique to its schema."""
    properties = schema.get("properties", {})
    if "species_distinguishable" in properties:
        return "identification"
    if "injury_present" in properties:
        return "assessment"
    if "headline" in properties:
        return "report"
    if "is_grounded" in properties:
        return "guardrail"
    return "unknown"


# ---------------------------------------------------------------------------
# Building blocks for the scenarios
# ---------------------------------------------------------------------------


def _candidate(
    common: str,
    scientific: str,
    confidence: float,
    group: str,
    genus_common: str,
    family: str,
    family_common: str,
) -> dict[str, Any]:
    return {
        "common_name": common,
        "scientific_name": scientific,
        "genus": scientific.split()[0],
        "genus_common_name": genus_common,
        "family": family,
        "family_common_name": family_common,
        "confidence": confidence,
        "animal_group": group,
    }


def _identification(
    candidates: list[dict[str, Any]],
    *,
    reasoning: str,
    question: str = "",
    options: list[str] | None = None,
    feature: str = "",
    distinguishable: bool = True,
) -> dict[str, Any]:
    return {
        "candidates": candidates,
        "species_distinguishable": distinguishable,
        "reasoning": reasoning,
        "needs_new_photo": False,
        "photo_quality_note": "",
        "next_question": question,
        "next_question_rationale": "Separates the leading candidates." if question else "",
        "next_question_options": options or [],
        "next_question_feature": feature,
    }


def _assessment(
    *, confident: bool, question: str = "", feature: str = "", **flags: Any
) -> dict[str, Any]:
    base = {
        "injury_present": False,
        "injury_confidence": 0.6,
        "wound": False,
        "bleeding": False,
        "entanglement": False,
        "swelling": False,
        "abnormal_posture": False,
        "respiratory_distress": False,
        "unresponsive": False,
        "emaciated": False,
        "mobility_concern": "unknown",
        "injury_summary": "",
        "near_people": False,
        "near_dogs": False,
        "near_road": False,
        "in_surf": False,
        "risk_of_being_stranded_further": False,
        "hazard_notes": "",
        "recommended_action": "",
        "reporter_instructions": [],
        "safety_guidance": "Please stay at least 50 yards (45 m) away and keep dogs leashed.",
        "environmental_rationale": "",
        "time_sensitivity_hours": 4.0,
        "is_confident": confident,
        "next_question": question,
        "next_question_rationale": "Would change the recommendation." if question else "",
        "next_question_options": ["yes", "no", "not sure"] if question else [],
        "next_question_feature": feature,
    }
    base.update(flags)
    return base


_APPROVED = {
    "is_grounded": True,
    "is_safe": True,
    "unsupported_claims": [],
    "unsafe_advice": [],
    "missing_critical_content": [],
    "notes": "",
}

_C_DOLPHIN = ("Common dolphin", "Delphinus delphis")
_B_DOLPHIN = ("Bottlenose dolphin", "Tursiops truncatus")
_PORPOISE = ("Harbour porpoise", "Phocoena phocoena")
_DELPHINIDAE = ("Delphinidae", "oceanic dolphins")


SCENARIOS: dict[str, dict[str, list[dict[str, Any]]]] = {
    # -- 1. Species is obvious from the photo: no identification questions. ---
    "sea_lion": {
        "identification": [
            _identification(
                [
                    _candidate("California sea lion", "Zalophus californianus", 0.94,
                               "pinniped", "California sea lions", "Otariidae", "eared seals"),
                    _candidate("Steller sea lion", "Eumetopias jubatus", 0.04,
                               "pinniped", "Steller sea lions", "Otariidae", "eared seals"),
                ],
                reasoning="External ear flaps, long fore-flippers, upright posture, "
                "and dark brown coat; size and location fit a California sea lion.",
            )
        ],
        "assessment": [
            _assessment(
                confident=False,
                question="Can you see anything wrapped around its neck or flippers, "
                "like netting, line, or a plastic strap?",
                feature="entanglement_check",
                injury_present=True,
                abnormal_posture=True,
                mobility_concern="limited",
                injury_summary="Holding its head low; possible material around the neck.",
            ),
            _assessment(
                confident=True,
                injury_present=True,
                injury_confidence=0.85,
                entanglement=True,
                wound=True,
                abnormal_posture=True,
                mobility_concern="limited",
                near_people=True,
                injury_summary="Green netting around the neck has cut into the skin.",
                hazard_notes="Beachgoers gathering nearby.",
                recommended_action="Entanglement response team with cutting gear.",
                reporter_instructions=[
                    "Keep people and dogs back at least 50 yards.",
                    "Do not try to remove the netting.",
                    "Stay in sight of the animal if it is safe to.",
                ],
                environmental_rationale="Rising tide may draw it into the water before "
                "a team arrives, which would end any chance of removing the net.",
                time_sensitivity_hours=2.0,
            ),
        ],
        "report": [
            {
                "headline": "Entangled California sea lion, Moss Landing, netting in neck",
                "summary": "Adult California sea lion (0.94) on the beach with green "
                "netting around the neck that has cut into the skin. Mobility "
                "limited. Rising tide.",
                "recommended_actions": [
                    "Dispatch an entanglement team with cutting gear.",
                    "Approach before high water, while the animal is on land.",
                ],
                "access_notes": "Access unknown.",
                "equipment_suggestions": ["Cutting pole", "Hoop net", "Herding boards"],
                "hazard_warnings": ["Crowd forming", "Sea lions move fast on sand"],
                "unknowns": ["How long the animal has been entangled"],
                "reporter_contact_note": "Reporter is on scene.",
            }
        ],
        "guardrail": [_APPROVED],
    },
    # -- 2. One question separates two look-alikes at species level. ---------
    "seal": {
        "identification": [
            _identification(
                [
                    _candidate("Harbor seal", "Phoca vitulina", 0.55, "pinniped",
                               "harbour seals", "Phocidae", "true seals"),
                    _candidate("Northern elephant seal", "Mirounga angustirostris", 0.35,
                               "pinniped", "elephant seals", "Phocidae", "true seals"),
                ],
                reasoning="No ear flaps and short fore-flippers: a true seal. The "
                "photo does not show scale, and a weaned elephant seal pup looks similar.",
                question="Roughly how long is it, compared to a person lying down?",
                options=["shorter", "about the same", "longer", "not sure"],
                feature="body_length",
            ),
            _identification(
                [
                    _candidate("Harbor seal", "Phoca vitulina", 0.93, "pinniped",
                               "harbour seals", "Phocidae", "true seals"),
                    _candidate("Northern elephant seal", "Mirounga angustirostris", 0.05,
                               "pinniped", "elephant seals", "Phocidae", "true seals"),
                ],
                reasoning="Shorter than a person, spotted coat, rounded head: harbour seal.",
            ),
        ],
        "assessment": [
            _assessment(
                confident=True,
                mobility_concern="none",
                injury_summary="No visible injury. Alert and resting.",
                recommended_action="No intervention. Seals rest on beaches normally.",
                reporter_instructions=[
                    "Leave the seal alone; resting on land is normal.",
                    "Keep dogs on a leash and away.",
                ],
                environmental_rationale="Healthy animal hauled out; tide not a concern.",
            )
        ],
        "report": [
            {
                "headline": "Resting harbour seal, no intervention needed",
                "summary": "Healthy harbour seal (0.93) hauled out and alert.",
                "recommended_actions": ["No response needed."],
                "access_notes": "",
                "equipment_suggestions": [],
                "hazard_warnings": [],
                "unknowns": [],
                "reporter_contact_note": "Reporter advised to keep distance.",
            }
        ],
        "guardrail": [_APPROVED],
    },
    # -- 3. Species cannot be separated from a distance: settle at family. ---
    "dolphin": {
        "identification": [
            _identification(
                [
                    _candidate(*_C_DOLPHIN, 0.45, "cetacean", "common dolphins",
                               *_DELPHINIDAE),
                    _candidate(*_B_DOLPHIN, 0.38, "cetacean", "bottlenose dolphins",
                               *_DELPHINIDAE),
                    _candidate(*_PORPOISE, 0.12, "cetacean", "harbour porpoises",
                               "Phocoenidae", "porpoises"),
                ],
                reasoning="Small grey cetacean on its side at the waterline; the head "
                "is partly hidden, so beak length is not visible.",
                question="Does it have a long, distinct beak, or a short rounded face?",
                options=["long beak", "short rounded face", "not sure"],
                feature="snout_shape",
            ),
            _identification(
                [
                    _candidate(*_C_DOLPHIN, 0.50, "cetacean", "common dolphins",
                               *_DELPHINIDAE),
                    _candidate(*_B_DOLPHIN, 0.44, "cetacean", "bottlenose dolphins",
                               *_DELPHINIDAE),
                    _candidate(*_PORPOISE, 0.02, "cetacean", "harbour porpoises",
                               "Phocoenidae", "porpoises"),
                ],
                reasoning="A distinct beak rules out a porpoise. Common and bottlenose "
                "differ in beak length and side colouring, which cannot be judged "
                "reliably from 50 yards in this light.",
                distinguishable=False,
            ),
        ],
        "assessment": [
            _assessment(
                confident=False,
                question="Is it breathing? You may see the blowhole on top of its head "
                "open and close every so often.",
                feature="breathing",
                mobility_concern="immobile",
            ),
            _assessment(
                confident=True,
                injury_present=True,
                injury_confidence=0.7,
                mobility_concern="immobile",
                abnormal_posture=True,
                risk_of_being_stranded_further=True,
                injury_summary="Alive, breathing, lying on its side and not moving.",
                recommended_action="Immediate stranding-network response.",
                reporter_instructions=[
                    "Do not push it back into the water.",
                    "Keep people and dogs away, and keep the blowhole clear of sand.",
                ],
                environmental_rationale="Falling tide will leave it further from the "
                "water; an out-of-water cetacean is always an emergency.",
                time_sensitivity_hours=1.0,
            ),
        ],
        "report": [
            {
                "headline": "Live stranded dolphin, immobile on its side, falling tide",
                "summary": "Oceanic dolphin, species unconfirmed (common 0.50, "
                "bottlenose 0.44) — confirm on arrival. Alive and breathing, "
                "immobile at the waterline.",
                "recommended_actions": [
                    "Dispatch a cetacean stranding team now.",
                    "Bring stretcher, wet sheets, and shade.",
                ],
                "access_notes": "Access unknown.",
                "equipment_suggestions": ["Stretcher", "Wet sheets", "Shade"],
                "hazard_warnings": ["Surf at the waterline"],
                "unknowns": ["Exact species", "Any internal injury"],
                "reporter_contact_note": "Reporter is on scene.",
            }
        ],
        "guardrail": [_APPROVED],
    },
    # -- 4. Not a marine mammal at all: this system still identifies it
    # correctly (TERRESTRIAL), but the rescue directory is marine-only, so
    # dispatch honestly returns no responder instead of a misleading match.
    "raccoon": {
        "identification": [
            _identification(
                [
                    _candidate(
                        "Raccoon", "Procyon lotor", 0.91, "terrestrial",
                        "raccoons", "Procyonidae", "procyonids",
                    ),
                ],
                reasoning="Masked face, ringed tail, and stocky build are "
                "distinctive and visible in the photo; this is a land mammal, "
                "not a marine one.",
            )
        ],
        "assessment": [
            _assessment(
                confident=True,
                injury_present=True,
                injury_confidence=0.6,
                abnormal_posture=True,
                mobility_concern="limited",
                near_people=True,
                injury_summary="Moving slowly and dragging a hind leg; no "
                "visible wound or bleeding.",
                recommended_action="Contact a local wildlife rehabilitator or "
                "animal control directly; this is outside the marine "
                "stranding network this system dispatches through.",
                reporter_instructions=[
                    "Keep well back and keep children and pets away.",
                    "Do not attempt to touch, feed, or corner the animal.",
                    "Raccoons can carry rabies -- do not handle it even if "
                    "it seems weak.",
                ],
                environmental_rationale="Not a coastal case; tide and marine "
                "weather are not relevant here.",
                time_sensitivity_hours=None,
            )
        ],
        "report": [
            {
                "headline": "Injured raccoon, limited mobility -- outside marine network",
                "summary": "Raccoon (0.91) with limited mobility, favouring "
                "a hind leg. Not a marine mammal; no stranding-network "
                "responder applies to this report.",
                "recommended_actions": [
                    "Reporter should contact a local wildlife rehabilitator "
                    "or animal control directly.",
                ],
                "access_notes": "Not applicable.",
                "equipment_suggestions": [],
                "hazard_warnings": ["Do not handle: rabies-vector species"],
                "unknowns": ["Cause of the leg injury"],
                "reporter_contact_note": "Reporter is on scene.",
            }
        ],
        "guardrail": [_APPROVED],
    },
}
