"""End-to-end conversations through the real pipeline, with a scripted model.

These run every step -- identification, taxonomy, assessment, severity,
report, guardrail, responder ranking -- with no network and no API key, by
swapping in `ScriptedLLMClient`. They are what caught the bug where reporter
answers were recorded but never re-processed.
"""

from __future__ import annotations

import pytest
from lifejacket.chatbot.playground import ChatPlayground
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.models.schemas import AnimalGroup, IncidentStatus, SeverityLevel, TaxonRank


@pytest.fixture(autouse=True)
def _no_geocoding(monkeypatch):
    """Responder ranking reverse-geocodes; keep tests off the network."""
    monkeypatch.setattr("lifejacket.services.pipeline.reverse_geocode", lambda *a: None)


def _run(scenario: str, answers: list[str]) -> tuple[ChatPlayground, ScriptedLLMClient]:
    client = ScriptedLLMClient.scenario(scenario)
    chat = ChatPlayground.full(client=client, live_context=False, verbose=False)
    for answer in answers:
        if chat.done:
            break
        chat.answer(answer)
    return chat, client


def test_obvious_species_needs_no_identification_questions():
    chat, client = _run("sea_lion", ["yes, green netting"])

    assert chat.state.identification_questions_asked == 0
    assert chat.state.identification.resolution.rank is TaxonRank.SPECIES
    # The entanglement answer reached the assessment agent and drove triage.
    assert chat.state.assessment.injury.entanglement
    assert chat.state.assessment.severity_level is SeverityLevel.CRITICAL
    assert [c.agent for c in client.calls] == [
        "identification", "assessment", "assessment", "validation", "report", "guardrail",
    ]


def test_one_answer_settles_the_species():
    chat, client = _run("seal", ["shorter"])

    resolution = chat.state.identification.resolution
    assert resolution.name == "Harbor seal"
    assert resolution.rank is TaxonRank.SPECIES
    assert chat.state.identification_questions_asked == 1
    # Identification ran twice: before and after the answer.
    assert [c.agent for c in client.calls].count("identification") == 2
    # The second prompt contains the reporter's answer.
    assert "shorter" in client.calls[1].prompt


def test_indistinguishable_species_settle_at_family_with_probabilities():
    chat, _ = _run("dolphin", ["long beak", "yes, breathing"])

    resolution = chat.state.identification.resolution
    assert resolution.rank is TaxonRank.FAMILY
    assert resolution.name == "Oceanic dolphins"
    assert {m.common_name for m in resolution.members} == {
        "Common dolphin", "Bottlenose dolphin",
    }
    assert chat.state.identification_questions_asked == 1
    assert chat.incident.status is IncidentStatus.AWAITING_DISPATCH


def test_healthy_animal_gets_guidance_only_and_no_responders():
    # Two answers: one for identification, one for the assessment question
    # that is now mandatory before triage runs.
    chat, _ = _run("seal", ["shorter", "looks normal"])
    assert chat.incident.status is IncidentStatus.GUIDANCE_ONLY
    assert chat.incident.dispatch_candidates == []


def test_identification_only_stops_before_assessment():
    client = ScriptedLLMClient.scenario("seal")
    chat = ChatPlayground.identification_only(client=client, live_context=False, verbose=False)
    chat.answer("shorter")

    assert chat.done
    assert chat.state.assessment is None
    assert {c.agent for c in client.calls} == {"identification"}


def test_assessment_only_skips_identification():
    client = ScriptedLLMClient.scenario("sea_lion")
    chat = ChatPlayground.assessment_only(
        species="California sea lion",
        scientific_name="Zalophus californianus",
        family="Otariidae",
        client=client,
        live_context=False,
        verbose=False,
    )
    chat.answer("yes, netting")

    assert chat.done
    assert "identification" not in {c.agent for c in client.calls}
    assert chat.state.assessment.severity_level is SeverityLevel.CRITICAL
    assert chat.incident.report is None  # stopped before the report


def test_report_includes_species_probabilities_for_the_guardrail():
    """The guardrail must see the breakdown, or it flags it as invented."""
    chat, client = _run("dolphin", ["long beak", "yes, breathing"])
    guardrail_prompt = next(c.prompt for c in client.calls if c.agent == "guardrail")
    assert "common dolphin 0.50" in guardrail_prompt
    assert "bottlenose dolphin 0.44" in guardrail_prompt


def test_a_photo_contradicting_the_flags_gets_questioned_and_corrected():
    """The case the consistency check exists for.

    The assessment agent records `wound: false` on an animal whose photo shows
    an open wound. Nothing downstream re-reads the picture, so without this
    check a responder would be sent out expecting a healthy animal.
    """
    client = ScriptedLLMClient.scenario("seal")
    # Overwrite the default "no conflicts" reply: first the checker spots the
    # contradiction and asks, then -- after the reporter confirms a wound and
    # the assessment agent re-runs -- it is satisfied.
    client.script["validation"] = [
        {
            "has_conflict": True,
            "conflicts": [
                {
                    "kind": "photo_vs_flags",
                    "recorded": "wound: false",
                    "observed": "an open wound is visible on the animal's flank",
                    "confidence": 0.9,
                    "field": "wound",
                }
            ],
            "next_question": "Is that an open wound on its side, or wet fur?",
            "next_question_rationale": "Photo appears to contradict the record.",
            "next_question_options": ["open wound", "wet fur", "cannot tell"],
            "next_question_feature": "wound_check",
            "notes": "Photo appears to show a wound the record denies.",
        },
        {
            "has_conflict": False,
            "conflicts": [],
            "next_question": "",
            "next_question_rationale": "",
            "next_question_options": [],
            "next_question_feature": "",
            "notes": "Resolved with the reporter.",
        },
    ]

    chat = ChatPlayground.full(client=client, live_context=False, verbose=False)
    chat.answer("shorter")                      # identification
    turn = chat.answer("looks normal")          # mandatory assessment question
    # The checker should now be asking about the contradiction.
    assert "wound" in (turn.message or "").lower()

    chat.answer("open wound")
    assert chat.done

    assert chat.state.validation_questions_asked == 1
    # Assessment re-ran after the correction, and the check ran twice.
    agents = [c.agent for c in client.calls]
    assert agents.count("validation") == 2
    assert agents.count("assessment") >= 3

    # Resolved, so nothing is outstanding -- but the audit trail keeps it,
    # because "the photo contradicted the record and the reporter confirmed a
    # wound" is worth knowing after the fact.
    assert chat.incident.metrics["validation_conflicts"] == []
    assert chat.incident.metrics["validation_conflicts_raised"][0]["field"] == "wound"


def test_non_marine_animal_is_identified_and_triaged_with_no_fake_dispatch():
    """A raccoon is not a marine mammal, but the system must still work for it.

    Identification, group-specific advice, and severity scoring should all
    behave normally. The one honest difference: the rescue directory is
    marine-only, so no responder is suggested -- an empty list, not a wrong
    (seal centre) one.
    """
    # Identification needs nothing here, but assessment must still ask once.
    chat, _ = _run("raccoon", ["looks normal"])

    assert chat.state.identification.animal_group is AnimalGroup.TERRESTRIAL
    assert chat.state.identification.is_confident

    assessment = chat.state.assessment
    assert assessment.injury.injury_present
    assert assessment.severity_level is not None  # real triage still ran
    assert "wildlife rehabilitator" in assessment.recommended_action

    assert chat.incident.dispatch_candidates == []
    assert chat.incident.status is IncidentStatus.AWAITING_DISPATCH
    assert chat.incident.report is not None


def test_a_yes_no_question_sent_without_options_still_reaches_the_reporter_with_buttons():
    """The assessment agent omitted options on 9 of 40 recorded questions."""
    client = ScriptedLLMClient.scenario("dolphin")
    asked = client.script["assessment"][0]
    asked["next_question"] = "Is the dolphin breathing?"
    asked["next_question_options"] = []

    chat = ChatPlayground.full(client=client, live_context=False, verbose=False)
    chat.answer("long beak")  # settles identification; assessment now asks

    last = [m for m in chat.state.transcript if m.agent_name == "assessment"][-1]
    assert last.content == "Is the dolphin breathing?"
    assert last.options == ["Yes", "No", "Not sure"]
