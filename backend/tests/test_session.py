"""Tests for the conversation state machine.

`decide_next_step` is a pure function, so the whole question-budget policy is
testable with no API key and no network.
"""

from __future__ import annotations

from lifejacket.agents.validation import Conflict, ValidationResult
from lifejacket.chatbot.session import (
    ConversationState,
    StepAction,
    decide_next_step,
    identification_stop_reason,
)
from lifejacket.config import settings
from lifejacket.models.schemas import (
    AnimalDetection,
    AnimalGroup,
    AssessmentResult,
    ClarifyingQuestion,
    ConversationStage,
    IdentificationResult,
    SpeciesCandidate,
)
from lifejacket.taxonomy import resolve_taxon


def _ready_state() -> ConversationState:
    """A state with a photo and a location -- ready for identification.

    Detection is marked as already run and found nothing, so these tests keep
    exercising identification; the detection step has its own tests below.
    """
    return ConversationState(
        incident_id="INC_test0001",
        photo_ids=["PHOTO_abc"],
        has_location=True,
        detections=[],
    )


def _species(name, scientific, confidence, family, group=AnimalGroup.PINNIPED):
    return SpeciesCandidate(
        common_name=name,
        scientific_name=scientific,
        confidence=confidence,
        family=family,
        animal_group=group,
    )


def _identification(
    candidates: list[SpeciesCandidate],
    *,
    question: str | None = "Roughly how long is it?",
    feature: str | None = "body_length",
    distinguishable: bool = True,
    needs_new_photo: bool = False,
) -> IdentificationResult:
    return IdentificationResult(
        candidates=candidates,
        resolution=resolve_taxon(candidates, settings.identification_confidence_threshold),
        species_distinguishable=distinguishable,
        needs_new_photo=needs_new_photo,
        next_question=(
            ClarifyingQuestion(question=question, feature=feature) if question else None
        ),
    )


HARBOR = ("Harbor seal", "Phoca vitulina")
ELEPHANT = ("Northern elephant seal", "Mirounga angustirostris")
COMMON = ("Common dolphin", "Delphinus delphis")
BOTTLENOSE = ("Bottlenose dolphin", "Tursiops truncatus")


class TestPrerequisites:
    def test_photo_is_requested_first(self):
        assert decide_next_step(ConversationState("INC_x")).action is StepAction.REQUEST_PHOTO

    def test_location_is_requested_before_identification(self):
        """Location informs which species are plausible, so it comes first."""
        state = ConversationState("INC_x", photo_ids=["PHOTO_1"])
        assert decide_next_step(state).action is StepAction.REQUEST_LOCATION

    def test_no_scripted_questions_identification_runs_immediately(self):
        """With photo and location, the next step is the agent -- not a script."""
        assert decide_next_step(_ready_state()).action is StepAction.RUN_IDENTIFICATION


class TestStoppingRule:
    def test_confident_species_stops_with_zero_questions(self):
        state = _ready_state()
        state.identification = _identification([_species(*HARBOR, 0.94, "Phocidae")])

        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT
        assert "species level" in identification_stop_reason(state)

    def test_confident_genus_stops(self):
        """Two species in one genus, pooled past the threshold, is enough."""
        state = _ready_state()
        state.identification = _identification(
            [
                _species("Long-beaked common dolphin", "Delphinus capensis", 0.50, "Delphinidae"),
                _species("Short-beaked common dolphin", "Delphinus delphis", 0.45, "Delphinidae"),
            ]
        )
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT
        assert "genus level" in identification_stop_reason(state)

    def test_confident_family_keeps_asking_while_a_question_can_help(self):
        """Family is not a stopping rank by default.

        Harbor 0.55 + elephant 0.35 pools to 0.90 for "true seals", but one
        question about size usually settles it -- so the agent should ask.
        """
        state = _ready_state()
        state.identification = _identification(
            [_species(*HARBOR, 0.55, "Phocidae"), _species(*ELEPHANT, 0.35, "Phocidae")]
        )
        assert state.identification.resolution.rank.value == "family"
        assert state.identification.is_confident

        assert decide_next_step(state).action is StepAction.ASK_CLARIFYING_QUESTION

    def test_family_is_accepted_when_species_cannot_be_separated(self):
        """The dolphin case: the agent says no question can help, so settle."""
        state = _ready_state()
        state.identification_questions_asked = 1
        state.identification = _identification(
            [
                _species(*COMMON, 0.50, "Delphinidae", AnimalGroup.CETACEAN),
                _species(*BOTTLENOSE, 0.44, "Delphinidae", AnimalGroup.CETACEAN),
            ],
            question=None,
            distinguishable=False,
        )
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT
        assert state.identification.resolution.rank.value == "family"
        assert "safe distance" in identification_stop_reason(state)

    def test_indistinguishable_flag_stops_even_if_a_question_was_offered(self):
        """The agent's own judgement that questions cannot help is respected."""
        state = _ready_state()
        state.identification = _identification(
            [_species(*COMMON, 0.50, "Delphinidae"), _species(*BOTTLENOSE, 0.44, "Delphinidae")],
            distinguishable=False,
        )
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT

    def test_family_can_be_made_a_stopping_rank(self, monkeypatch):
        monkeypatch.setattr(settings, "confident_taxon_ranks", ["species", "genus", "family"])
        state = _ready_state()
        state.identification = _identification(
            [_species(*HARBOR, 0.55, "Phocidae"), _species(*ELEPHANT, 0.35, "Phocidae")]
        )
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT

    def test_low_confidence_asks_a_question(self):
        state = _ready_state()
        state.identification = _identification(
            [_species(*HARBOR, 0.50, "Phocidae"), _species(*ELEPHANT, 0.20, "Phocidae")]
        )
        decision = decide_next_step(state)
        assert decision.action is StepAction.ASK_CLARIFYING_QUESTION
        assert "question 1 of 5" in decision.reason


class TestLowConfidenceMustKeepAsking:
    """Below `identification_min_confidence_to_settle`, "no question can help"
    is not trusted on its own -- a three-way 0.30/0.30/0.30 split across
    unrelated families is not the same situation as a confident family-level
    pool, even though the agent reports the same `species_distinguishable`
    flag for both. The agent must try a generic fallback clue before settling.
    """

    def test_low_confidence_with_no_question_tries_a_fallback(self):
        state = _ready_state()
        state.identification = _identification(
            [
                _species("California sea lion", "Zalophus californianus", 0.30, "Otariidae"),
                _species(*HARBOR, 0.30, "Phocidae"),
                _species(*ELEPHANT, 0.30, "Phocidae"),
            ],
            question=None,
            distinguishable=False,
        )
        decision = decide_next_step(state)
        assert decision.action is StepAction.ASK_CLARIFYING_QUESTION
        assert decision.question is not None
        assert decision.question.feature not in state.probed_features

    def test_low_confidence_falls_back_past_a_repeated_feature_too(self):
        """A repeated feature is skipped in favour of the next fallback clue."""
        state = _ready_state()
        state.probed_features = ["body_length"]
        state.identification = _identification(
            [_species(*HARBOR, 0.30, "Phocidae")], feature="body_length"
        )
        decision = decide_next_step(state)
        assert decision.action is StepAction.ASK_CLARIFYING_QUESTION
        assert decision.question.feature == "behavior"

    def test_low_confidence_settles_once_fallbacks_are_exhausted(self):
        state = _ready_state()
        state.probed_features = ["body_length", "behavior", "coloration", "limb_shape"]
        state.identification = _identification(
            [_species(*HARBOR, 0.30, "Phocidae")], question=None, distinguishable=False
        )
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT

    def test_low_confidence_still_respects_the_question_budget(self):
        state = _ready_state()
        state.identification_questions_asked = settings.max_identification_questions
        state.identification = _identification(
            [_species(*HARBOR, 0.30, "Phocidae")], question=None, distinguishable=False
        )
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT
        assert "budget spent" in identification_stop_reason(state)


class TestQuestionBudget:
    def test_never_more_than_five_questions(self):
        state = _ready_state()
        state.identification_questions_asked = settings.max_identification_questions
        state.identification = _identification([_species(*HARBOR, 0.40, "Phocidae")])

        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT
        assert "budget spent" in identification_stop_reason(state)

    def test_already_probed_feature_is_not_asked_again(self):
        """Feature-based dedup, so a rephrased duplicate cannot slip through.

        Confidence (0.85) is kept above `identification_min_confidence_to_settle`
        so this exercises the dedup rule itself, not the low-confidence fallback
        covered by `TestLowConfidenceMustKeepAsking` below.
        """
        state = _ready_state()
        state.probed_features = ["body_length"]
        state.identification = _identification(
            [_species(*HARBOR, 0.85, "Phocidae")], feature="body_length"
        )
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT

    def test_assessment_budget_is_separate(self):
        state = _ready_state()
        state.identification_questions_asked = 5
        state.identification = _identification([_species(*HARBOR, 0.95, "Phocidae")])
        state.assessment = AssessmentResult(
            is_confident=False,
            next_question=ClarifyingQuestion(question="Is it bleeding?", feature="bleeding"),
        )
        assert decide_next_step(state).action is StepAction.ASK_CLARIFYING_QUESTION


class TestAnswersAreActedOn:
    """Regression tests: a reply must make the agent that asked run again.

    The first version recorded answers in the transcript but never re-ran the
    agent, so identification stayed at its first guess regardless of what the
    reporter said.
    """

    def test_answering_identification_reruns_identification(self):
        state = _ready_state()
        state.identification = _identification(
            [_species(*HARBOR, 0.55, "Phocidae"), _species(*ELEPHANT, 0.35, "Phocidae")]
        )
        question = state.identification.next_question
        state.stage = ConversationStage.IDENTIFYING
        state.add_agent_message(question.question, "identification", question)
        state.add_reporter_message("shorter")

        assert state.identification_stale
        assert decide_next_step(state).action is StepAction.RUN_IDENTIFICATION

    def test_answering_assessment_reruns_assessment_not_identification(self):
        state = _ready_state()
        state.identification = _identification([_species(*HARBOR, 0.95, "Phocidae")])
        question = ClarifyingQuestion(question="Anything wrapped around it?", feature="ent")
        state.assessment = AssessmentResult(is_confident=False, next_question=question)
        state.stage = ConversationStage.ASSESSING
        state.add_agent_message(question.question, "assessment", question)
        state.add_reporter_message("yes, netting")

        assert not state.identification_stale
        assert state.assessment_stale
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT

    def test_volunteered_message_goes_to_the_active_agent(self):
        state = _ready_state()
        state.identification = _identification([_species(*HARBOR, 0.50, "Phocidae")])
        state.stage = ConversationStage.IDENTIFYING
        state.add_reporter_message("it has spots all over")
        assert state.identification_stale


class TestPhotoRetake:
    def test_unusable_photo_prompts_one_retake(self):
        state = _ready_state()
        state.identification = _identification(
            [_species(*HARBOR, 0.2, "Phocidae")], needs_new_photo=True
        )
        assert decide_next_step(state).action is StepAction.REQUEST_BETTER_PHOTO

    def test_retake_is_only_offered_once(self):
        state = _ready_state()
        state.better_photo_requested = True
        state.identification = _identification(
            [_species(*HARBOR, 0.2, "Phocidae")], needs_new_photo=True
        )
        assert decide_next_step(state).action is StepAction.ASK_CLARIFYING_QUESTION

    def test_no_retake_when_already_confident(self):
        """If we are confident, the photo was evidently good enough."""
        state = _ready_state()
        state.identification = _identification(
            [_species(*HARBOR, 0.95, "Phocidae")], needs_new_photo=True
        )
        assert decide_next_step(state).action is StepAction.RUN_ASSESSMENT


class TestConsistencyCheck:
    """When a contradiction is worth interrupting the reporter for.

    Three things have to line up: a conflict solid enough to act on, a
    question a reporter standing on a beach could answer, and budget left.
    """

    def _checked(self, **validation) -> ConversationState:
        state = _ready_state()
        state.identification = _identification([_species(*HARBOR, 0.95, "Phocidae")])
        state.assessment = AssessmentResult(is_confident=True)
        state.assessment_questions_asked = 1
        state.validation = ValidationResult(**validation)
        return state

    def _conflict(self, confidence: float) -> Conflict:
        return Conflict(
            kind="photo_vs_flags",
            recorded="wound: false",
            observed="an open wound is visible on the left flank",
            confidence=confidence,
            field="wound",
        )

    def test_a_solid_conflict_asks_the_reporter(self):
        state = self._checked(
            has_conflict=True,
            conflicts=[self._conflict(0.9)],
            next_question=ClarifyingQuestion(
                question="Is that an open wound or wet fur?", feature="wound_check"
            ),
        )
        decision = decide_next_step(state)
        assert decision.action is StepAction.ASK_CLARIFYING_QUESTION
        assert "wound: false" in decision.reason

    def test_a_low_confidence_hunch_does_not_interrupt(self):
        """A 0.4 guess that a shadow might be a wound is not worth a question."""
        state = self._checked(
            has_conflict=True,
            conflicts=[self._conflict(0.4)],
            next_question=ClarifyingQuestion(question="Is that a wound?", feature="w"),
        )
        assert decide_next_step(state).action is StepAction.FINALISE

    def test_a_conflict_the_reporter_cannot_settle_does_not_ask(self):
        """Two flags contradicting each other is not theirs to resolve."""
        state = self._checked(
            has_conflict=True,
            conflicts=[
                Conflict(
                    kind="flags_vs_flags",
                    recorded="bleeding: true, wound: false",
                    observed="bleeding implies a wound",
                    confidence=0.95,
                    field="wound",
                )
            ],
        )
        assert decide_next_step(state).action is StepAction.FINALISE

    def test_no_conflict_finalises(self):
        state = self._checked(has_conflict=False, notes="No conflicts found.")
        assert decide_next_step(state).action is StepAction.FINALISE

    def test_budget_stops_the_loop(self):
        """Each answer re-runs assessment and re-checks, so this must terminate."""
        state = self._checked(
            has_conflict=True,
            conflicts=[self._conflict(0.9)],
            next_question=ClarifyingQuestion(question="Wound?", feature="wound_check"),
        )
        state.validation_questions_asked = settings.max_validation_questions
        assert decide_next_step(state).action is StepAction.FINALISE

    def test_a_changed_record_is_rechecked(self):
        """Answering re-runs assessment, which invalidates the previous check."""
        state = self._checked(has_conflict=False)
        state.validation_stale = True
        assert decide_next_step(state).action is StepAction.RUN_VALIDATION

    def test_an_answer_to_a_conflict_goes_to_the_assessment_agent(self):
        """The reporter is correcting a flag, and assessment owns the flags."""
        state = self._checked(has_conflict=False)
        state.stage = ConversationStage.VALIDATING
        question = ClarifyingQuestion(question="Wound or wet fur?", feature="wound_check")
        state.add_agent_message(question.question, "validation", question)
        state.add_reporter_message("it is an open wound")

        assert state.assessment_stale
        assert state.validation_stale


class TestFinalisation:
    def test_confident_assessment_runs_the_consistency_check_first(self):
        """Nothing finalises before the record is checked against the photo."""
        state = _ready_state()
        state.identification = _identification([_species(*HARBOR, 0.95, "Phocidae")])
        state.assessment = AssessmentResult(is_confident=True)
        state.assessment_questions_asked = 1
        assert decide_next_step(state).action is StepAction.RUN_VALIDATION

    def test_confident_assessment_finalises(self):
        state = _ready_state()
        state.identification = _identification([_species(*HARBOR, 0.95, "Phocidae")])
        state.assessment = AssessmentResult(is_confident=True)
        # One assessment question is mandatory, so confidence only ends the
        # conversation once something has actually been asked.
        state.assessment_questions_asked = 1
        state.validation = ValidationResult(has_conflict=False)
        assert decide_next_step(state).action is StepAction.FINALISE

    def test_confident_assessment_still_asks_one_question_first(self):
        """A photo shows a moment; breathing and entanglement do not.

        Confidence on the first pass is confidence about the image, so triage
        never runs on zero answers.
        """
        state = _ready_state()
        state.identification = _identification([_species(*HARBOR, 0.95, "Phocidae")])
        state.assessment = AssessmentResult(is_confident=True)

        decision = decide_next_step(state)
        assert decision.action is StepAction.ASK_CLARIFYING_QUESTION
        assert decision.question is not None
        assert "one question is required" in decision.reason

    def test_mandatory_question_uses_the_agent_s_own_when_offered(self):
        state = _ready_state()
        state.identification = _identification([_species(*HARBOR, 0.95, "Phocidae")])
        state.assessment = AssessmentResult(
            is_confident=True,
            next_question=ClarifyingQuestion(
                question="Is it bleeding?", feature="bleeding"
            ),
        )
        assert decide_next_step(state).question.question == "Is it bleeding?"

    def test_mandatory_question_gives_up_when_every_fallback_is_used(self):
        """The rule cannot invent a question that does not exist."""
        state = _ready_state()
        state.probed_features = ["breathing", "entanglement_check", "movement_since_arrival"]
        state.identification = _identification([_species(*HARBOR, 0.95, "Phocidae")])
        state.assessment = AssessmentResult(is_confident=True)
        state.validation = ValidationResult(has_conflict=False)
        assert decide_next_step(state).action is StepAction.FINALISE


def _two_animals_state() -> ConversationState:
    state = _ready_state()
    state.detections = [
        AnimalDetection(box=[200, 0, 890, 700], description="dark animal in the water"),
        AnimalDetection(box=[240, 640, 500, 800], description="white bird"),
    ]
    return state


class TestDetectionStep:
    def test_detection_runs_before_identification(self):
        state = _ready_state()
        state.detections = None
        assert decide_next_step(state).action is StepAction.RUN_DETECTION

    def test_nothing_found_goes_straight_to_identification(self):
        assert decide_next_step(_ready_state()).action is StepAction.RUN_IDENTIFICATION

    def test_one_animal_needs_no_choice(self):
        state = _ready_state()
        state.detections = [AnimalDetection(box=[0, 0, 500, 500], description="seal")]
        assert decide_next_step(state).action is StepAction.RUN_IDENTIFICATION
        assert state.chosen_detection is None  # whole photo, not a crop

    def test_several_animals_ask_which(self):
        assert decide_next_step(_two_animals_state()).action is StepAction.ASK_WHICH_ANIMAL

    def test_choice_unlocks_identification_on_that_animal(self):
        state = _two_animals_state()
        state.select_animal(1)
        assert decide_next_step(state).action is StepAction.RUN_IDENTIFICATION
        assert state.chosen_detection.description == "white bird"

    def test_numbered_reply_selects(self):
        state = _two_animals_state()
        state.add_agent_message(
            "Which?", "detection", ClarifyingQuestion(question="Which?", options=["1. a", "2. b"])
        )
        state.add_reporter_message("2. white bird")
        assert state.selected_detection == 1
        assert not state.identification_stale

    def test_unreadable_reply_asks_again(self):
        state = _two_animals_state()
        state.add_agent_message(
            "Which?", "detection", ClarifyingQuestion(question="Which?", options=["1. a", "2. b"])
        )
        state.add_reporter_message("the left one")
        assert state.selected_detection is None
        assert decide_next_step(state).action is StepAction.ASK_WHICH_ANIMAL

    def test_out_of_range_number_is_ignored(self):
        state = _two_animals_state()
        state.add_agent_message(
            "Which?", "detection", ClarifyingQuestion(question="Which?", options=["1. a", "2. b"])
        )
        state.add_reporter_message("7")
        assert state.selected_detection is None

    def test_changing_the_choice_restarts_identification(self):
        state = _two_animals_state()
        state.select_animal(0)
        state.identification = IdentificationResult(
            candidates=[_species("Harbor seal", "Phoca vitulina", 0.5, "Phocidae")]
        )
        state.identification_questions_asked = 3
        state.probed_features = ["body_length"]
        state.add_reporter_message("long")

        state.select_animal(1)

        assert state.identification is None
        assert state.identification_questions_asked == 0
        assert state.probed_features == []
        assert [message.content for message in state.transcript] == ["long"]
        assert state.active_transcript == []
        assert decide_next_step(state).action is StepAction.RUN_IDENTIFICATION

    def test_invalid_index_is_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            _two_animals_state().select_animal(5)
