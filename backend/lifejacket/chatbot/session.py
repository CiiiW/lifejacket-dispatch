"""The conversation state machine.

The prototype drove its conversation with `while True: input()` inside a
notebook. That cannot work behind an HTTP API, where each reporter reply is a
separate request, possibly minutes later, possibly from a phone that went to
sleep in between.

So the conversation is modelled as **state plus a decision function**:

    state = ConversationState(...)          # serialisable, lives in the DB
    decision = decide_next_step(state)      # pure function, no I/O

`decide_next_step` contains all the stopping logic and no side effects, which
means the whole question-budget policy is unit-testable without an API key.
The orchestration -- calling agents, writing rows -- lives in
`services/pipeline.py`.

There are **no scripted questions**. Once a photo and a location arrive, every
question comes from an agent and is chosen for that photo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lifejacket.config import settings
from lifejacket.models.schemas import (
    AssessmentResult,
    ChatMessage,
    ChatRole,
    ClarifyingQuestion,
    ConversationStage,
    IdentificationResult,
)


class StepAction(str, Enum):
    """What the system should do next."""

    REQUEST_PHOTO = "request_photo"
    REQUEST_LOCATION = "request_location"
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"
    REQUEST_BETTER_PHOTO = "request_better_photo"
    RUN_IDENTIFICATION = "run_identification"
    RUN_ASSESSMENT = "run_assessment"
    FINALISE = "finalise"


@dataclass
class Decision:
    """The next step, with the reason it was chosen.

    `reason` is recorded with the incident. The 0.90 confidence threshold is
    unvalidated -- 50 of 485 high-confidence answers in the research data were
    wrong -- so every stop decision says *why* it stopped, for calibrating
    later against what responders actually found.
    """

    action: StepAction
    question: ClarifyingQuestion | None = None
    reason: str = ""


@dataclass
class ConversationState:
    """Everything needed to resume a conversation from scratch.

    Deliberately plain data: no clients, no database handles, no open sockets.
    It serialises to JSON and back, so a reporter can close the app mid-intake
    and pick up where they left off.
    """

    incident_id: str
    stage: ConversationStage = ConversationStage.AWAITING_PHOTO

    photo_ids: list[str] = field(default_factory=list)
    has_location: bool = False

    #: Full conversation, reporter and agent turns interleaved. This is the
    #: only record of what the reporter said -- the agents read it every turn.
    transcript: list[ChatMessage] = field(default_factory=list)

    identification: IdentificationResult | None = None
    assessment: AssessmentResult | None = None

    identification_questions_asked: int = 0
    assessment_questions_asked: int = 0
    #: A retake is offered at most once; asking repeatedly frustrates reporters
    #: and the second photo is rarely better.
    better_photo_requested: bool = False

    #: Features already asked about, so the same discriminator is not asked
    #: twice in different words. Matching on feature rather than question text
    #: fixes the prototype's exact-string dedup, which any rephrasing defeated.
    probed_features: list[str] = field(default_factory=list)

    #: The agent question currently awaiting an answer, if any, and which
    #: agent asked it ("identification" or "assessment").
    pending_question: ClarifyingQuestion | None = None
    pending_agent: str | None = None

    #: Set when the reporter has said something an agent has not yet seen.
    #: The agent must run again before anything else is decided -- otherwise
    #: an answer would be recorded but never acted on.
    identification_stale: bool = False
    assessment_stale: bool = False

    #: Why identification stopped, e.g. "confident at genus level". Kept for
    #: the evaluation notebook.
    identification_stop_reason: str | None = None

    # --- Transcript helpers ------------------------------------------------

    def add_agent_message(
        self, content: str, agent_name: str, question: ClarifyingQuestion | None = None
    ) -> None:
        """Record an agent turn and mark it as awaiting a reply."""
        self.transcript.append(
            ChatMessage(
                role=ChatRole.AGENT,
                content=content,
                agent_name=agent_name,
                feature=question.feature if question else None,
                options=question.options if question else [],
            )
        )
        if question:
            self.pending_question = question
            self.pending_agent = agent_name
            if question.feature and question.feature not in self.probed_features:
                self.probed_features.append(question.feature)

    def add_reporter_message(self, content: str) -> None:
        """Record a reporter reply and mark the relevant agent as needing to rerun.

        The reply goes to whichever agent asked the pending question. A message
        volunteered with nothing pending ("it just moved into the water") goes
        to whichever agent is currently active.
        """
        self.transcript.append(
            ChatMessage(
                role=ChatRole.REPORTER,
                content=content,
                feature=self.pending_question.feature if self.pending_question else None,
            )
        )

        recipient = self.pending_agent or {
            ConversationStage.IDENTIFYING: "identification",
            ConversationStage.ASSESSING: "assessment",
        }.get(self.stage)
        if recipient == "identification":
            self.identification_stale = True
        elif recipient == "assessment":
            self.assessment_stale = True

        self.pending_question = None
        self.pending_agent = None

    @property
    def awaiting_answer(self) -> bool:
        """True when an agent question has been asked and not yet answered."""
        return self.pending_question is not None


def decide_next_step(state: ConversationState) -> Decision:
    """Work out the next step. Pure function -- no I/O, no mutation.

    The order of checks *is* the policy:

    1. Prerequisites: a photo and a location, since everything depends on them.
    2. Identification, until confident, out of useful questions, or out of budget.
    3. Assessment, likewise.
    4. Finalise.
    """
    # --- 1. Prerequisites ---
    if not state.photo_ids:
        return Decision(
            action=StepAction.REQUEST_PHOTO,
            reason="No photo submitted yet; identification cannot start.",
        )

    if not state.has_location:
        # Required, not optional: location drives the tide and weather lookups,
        # informs which species are plausible, and decides who may respond.
        return Decision(
            action=StepAction.REQUEST_LOCATION,
            reason="Location is needed for species range, tide, weather, and routing.",
        )

    # --- 2. Identification ---
    if state.identification is None:
        return Decision(
            action=StepAction.RUN_IDENTIFICATION,
            reason="Photo and location received; first look at the animal.",
        )
    if state.identification_stale:
        return Decision(
            action=StepAction.RUN_IDENTIFICATION,
            reason="Reporter answered; updating the identification.",
        )

    identification_decision = _decide_identification(state)
    if identification_decision is not None:
        return identification_decision

    # --- 3. Assessment ---
    if state.assessment is None:
        return Decision(
            action=StepAction.RUN_ASSESSMENT,
            reason=state.identification_stop_reason
            or "Identification settled; assessing condition and situation.",
        )
    if state.assessment_stale:
        return Decision(
            action=StepAction.RUN_ASSESSMENT,
            reason="Reporter answered; updating the assessment.",
        )

    assessment_decision = _decide_assessment(state)
    if assessment_decision is not None:
        return assessment_decision

    # --- 4. Done ---
    return Decision(
        action=StepAction.FINALISE,
        reason="Identification and assessment complete; writing the report.",
    )


def identification_stop_reason(state: ConversationState) -> str | None:
    """Why identification should stop now, or None if it should keep asking.

    Exposed separately from `decide_next_step` so the pipeline can record the
    reason, and so the notebooks can show it.

    The rule, in order:

    1. **Confident at a stopping rank** (species or genus by default) -> stop.
    2. **Out of questions** (5 by default) -> stop with the best answer so far,
       whatever its rank or confidence.
    3. **Agent says no question can help** -> stop, *unless* confidence is
       below `identification_min_confidence_to_settle`. Below that bar, "no
       question can help" is not trustworthy enough to settle on its own --
       there is always a fallback clue to try (see
       `_fallback_identification_question`) while budget remains. This is how
       a family-level answer such as "oceanic dolphin" is still reached when
       genuinely warranted: the species cannot be told apart from a safe
       distance, but pooled confidence is still high enough to trust that call.
    4. **Agent's question repeats a feature already asked about** -> stop,
       unless a fallback clue not yet asked about still exists.

    Retake requests are handled before this is consulted (see
    `_decide_identification`), because no question fixes a dark blur.
    """
    result = state.identification
    assert result is not None

    resolution = result.resolution
    if (
        resolution is not None
        and resolution.meets_threshold
        and resolution.rank.value in settings.confident_taxon_ranks
    ):
        return (
            f"Confident at {resolution.rank.value} level: "
            f"{resolution.name} ({resolution.confidence:.2f})."
        )

    asked = state.identification_questions_asked
    limit = settings.max_identification_questions
    if asked >= limit:
        return f"Question budget spent ({asked} of {limit}); proceeding with best answer."

    low_confidence = result.confidence < settings.identification_min_confidence_to_settle

    question = result.next_question
    if question is None or not question.question.strip() or not result.species_distinguishable:
        if low_confidence and _fallback_identification_question(state) is not None:
            return None
        rank = resolution.rank.value if resolution else "unknown"
        return (
            "No question can separate the remaining candidates from a safe "
            f"distance; settling at {rank} level."
        )

    if question.feature and question.feature in state.probed_features:
        if low_confidence and _fallback_identification_question(state) is not None:
            return None
        return f"Agent repeated an already-asked feature ({question.feature}); stopping."

    return None


#: Generic clues to fall back on when the agent is below
#: `identification_min_confidence_to_settle` but has no discriminating
#: question left of its own -- not species-specific, but often enough to
#: raise confidence past the bar instead of settling on a guess.
_FALLBACK_IDENTIFICATION_QUESTIONS: list[ClarifyingQuestion] = [
    ClarifyingQuestion(
        question="Roughly how big is it, compared to a person lying down?",
        options=["much smaller", "about the same", "much longer", "not sure"],
        feature="body_length",
    ),
    ClarifyingQuestion(
        question="What is it doing right now?",
        options=["lying still", "moving around", "looking at you", "not sure"],
        feature="behavior",
    ),
    ClarifyingQuestion(
        question="Any obvious color or pattern -- spots, stripes, or patches?",
        options=["solid color", "spots", "patches", "not sure"],
        feature="coloration",
    ),
    ClarifyingQuestion(
        question="Can you see ears, flippers, or fins, and roughly what shape?",
        options=["small ear flaps", "no visible ears", "fins/flippers only", "not sure"],
        feature="limb_shape",
    ),
]


def _fallback_identification_question(state: ConversationState) -> ClarifyingQuestion | None:
    """The next not-yet-asked generic clue, or None if all have been used."""
    for question in _FALLBACK_IDENTIFICATION_QUESTIONS:
        if question.feature not in state.probed_features:
            return question
    return None


def _decide_identification(state: ConversationState) -> Decision | None:
    """Continue identification, or None to move on to assessment."""
    result = state.identification
    assert result is not None

    # An unusable photo is worth exactly one retake request -- unless we are
    # already confident, in which case the photo was evidently good enough.
    if (
        result.needs_new_photo
        and not state.better_photo_requested
        and not result.is_confident
    ):
        return Decision(
            action=StepAction.REQUEST_BETTER_PHOTO,
            reason=result.photo_quality_note
            or "The photo is not clear enough to identify the animal.",
        )

    if identification_stop_reason(state) is not None:
        return None

    confidence = result.confidence
    question = result.next_question
    reason = (
        f"Best answer so far is {result.display_name} at {confidence:.2f}; "
        f"asking question {state.identification_questions_asked + 1} of "
        f"{settings.max_identification_questions}."
    )
    if (
        question is None
        or not question.question.strip()
        or (question.feature and question.feature in state.probed_features)
    ):
        # Reached only below identification_min_confidence_to_settle, where
        # identification_stop_reason refused to accept "no question left" as
        # a reason to stop (see its rule 3/4).
        question = _fallback_identification_question(state)
        reason = (
            f"Confidence is only {confidence:.2f} and the agent had no "
            "discriminating question left; asking a general clue instead of "
            f"settling (question {state.identification_questions_asked + 1} "
            f"of {settings.max_identification_questions})."
        )
    return Decision(
        action=StepAction.ASK_CLARIFYING_QUESTION,
        question=question,
        reason=reason,
    )


def _decide_assessment(state: ConversationState) -> Decision | None:
    """Continue assessment, or None to finalise."""
    result = state.assessment
    assert result is not None

    if result.is_confident:
        return None

    if state.assessment_questions_asked >= settings.max_assessment_questions:
        return None

    if result.next_question is None or not result.next_question.question.strip():
        return None

    feature = result.next_question.feature
    if feature and feature in state.probed_features:
        return None

    return Decision(
        action=StepAction.ASK_CLARIFYING_QUESTION,
        question=result.next_question,
        reason=(
            "Assessment is not yet confident; asking question "
            f"{state.assessment_questions_asked + 1} of {settings.max_assessment_questions}."
        ),
    )
