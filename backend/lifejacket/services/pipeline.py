"""The end-to-end workflow. **Start here to understand the system.**

One reported animal, from first photo to a report in front of a coordinator:

    1. Reporter submits a photo and shares their location.
    2. Environmental context is gathered (tide, weather, place name).
    3. IdentificationAgent looks at the photo and asks its own questions -- up
       to 5, chosen for this photo -- until the species (or genus, or family)
       is confident, or no question can help.
    4. AssessmentAgent asks up to 5 more about the animal's condition and
       surroundings.
    5. Severity is computed deterministically from those observations.
    6. ReportAgent writes the responder-facing report.
    7. GuardrailAgent checks it for invented claims and unsafe advice.
    8. Nearby duplicate reports are detected and linked.
    9. Rescue organisations are ranked for a human coordinator to approve.

The pipeline is **step-driven, not a loop.** Each call to `advance` performs
at most one reporter-facing step and returns, because every reporter answer
arrives as a separate HTTP request. State lives in `ConversationState`.

**When a model call fails** (after `LLMClient`'s own retries), the pipeline
does not raise. What it does instead depends on the step:

- Identification or assessment: the reporter is asked to try again; nothing
  they have said is lost, and the next request re-runs the same step.
- Report: the incident still goes to coordinators, with the assessment
  findings but no written report, held for human review.
- Guardrail: the report is held for human review, as if the check had failed.

Every retry, failure, and fail-safe is recorded on the incident by
`services/health.py`, so a coordinator can see that it happened.

Two constructor options exist mainly for the notebooks:

- `session=None` runs fully in memory: nothing is saved, and duplicate
  detection (which needs the database) is skipped. Everything else -- agents,
  taxonomy, severity, dispatch ranking -- is the same code the API runs.
- `stop_at={StepAction.RUN_ASSESSMENT}` halts before that step, so one
  chatbot can be tested on its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from lifejacket.agents.assessment import AssessmentAgent
from lifejacket.agents.base import Agent, AgentError
from lifejacket.agents.guardrail import GuardrailAgent, GuardrailVerdict
from lifejacket.agents.identification import IdentificationAgent
from lifejacket.agents.report import ReportAgent
from lifejacket.chatbot.session import (
    ConversationState,
    Decision,
    StepAction,
    decide_next_step,
    identification_stop_reason,
)
from lifejacket.config import settings
from lifejacket.context.environment import gather_context, summarise_for_prompt
from lifejacket.context.geocode import reverse_geocode
from lifejacket.dispatch.duplicates import find_duplicate, is_probable_duplicate
from lifejacket.dispatch.matching import rank_centers
from lifejacket.dispatch.severity import recommended_action, score_severity
from lifejacket.llm.client import ImageInput, LLMClient
from lifejacket.models import repository
from lifejacket.models.schemas import (
    ConversationStage,
    DispatchCandidate,
    GeoPoint,
    Incident,
    IncidentReport,
    IncidentStatus,
    SeverityLevel,
)
from lifejacket.services import health
from lifejacket.taxonomy import describe_resolution

logger = logging.getLogger(__name__)

#: Shown to the reporter when identification or assessment could not run.
#: Promises nothing about a response, and repeats the one instruction that
#: matters while they wait.
SERVICE_RETRY_MESSAGE = (
    "Sorry, we could not process that just now. Everything you have sent so far "
    "is saved. Please try again in a moment, and keep your distance from the "
    "animal while you wait."
)


@dataclass
class TurnResult:
    """What to show the reporter after one step of the pipeline."""

    #: The message to display, if any.
    message: str | None = None
    #: Tap-able answers, when the question has a small fixed set.
    options: list[str] = field(default_factory=list)
    #: True when the pipeline is waiting on the reporter.
    awaiting_reply: bool = False
    #: True when intake is finished (or halted by `stop_at`).
    complete: bool = False
    #: Which step ran, for the client to drive its UI (spinner, camera, map).
    action: StepAction | None = None
    #: Why this step was chosen. Logged, and shown in the notebooks.
    reason: str = ""


class IntakePipeline:
    """Drives one reporter's intake conversation.

    Args:
        session: Database session, or None to run in memory (notebooks).
        client: LLM client shared by all four agents. Defaults to the real
            Vertex client; pass `ScriptedLLMClient` to run offline.
        stop_at: Steps to halt before, instead of running them.
    """

    def __init__(
        self,
        session: Session | None = None,
        client: LLMClient | None = None,
        stop_at: set[StepAction] | None = None,
    ) -> None:
        self.session = session
        self.stop_at = stop_at or set()
        self.identification_agent = IdentificationAgent(client)
        self.assessment_agent = AssessmentAgent(client)
        self.report_agent = ReportAgent(client)
        self.guardrail_agent = GuardrailAgent(client)

    # -- Entry points -------------------------------------------------------

    def start_incident(
        self, reporter_id: str | None = None, reporter_phone: str | None = None
    ) -> tuple[Incident, ConversationState]:
        """Create a new, empty incident awaiting a photo."""
        incident = Incident(
            incident_id=repository.new_incident_id(),
            status=IncidentStatus.INTAKE,
            reporter_id=reporter_id,
            reporter_phone=reporter_phone,
        )
        self._save(incident)
        return incident, ConversationState(incident_id=incident.incident_id)

    def set_location(
        self, incident: Incident, state: ConversationState, location: GeoPoint
    ) -> None:
        """Attach the reporter's location and gather environmental context.

        Happens before identification because the location informs which
        species are plausible, not just what the tide is doing.
        """
        state.has_location = True
        context = gather_context(location)
        incident.environment = context
        # `gather_context` fills in a resolved place name when none was given.
        incident.location = context.location

        if context.unavailable:
            logger.info(
                "Incident %s has partial context; unavailable: %s",
                incident.incident_id,
                ", ".join(context.unavailable),
            )
        self._save(incident)

    def attach_photo(self, state: ConversationState, photo_id: str) -> None:
        """Register an uploaded photo with the conversation."""
        if photo_id not in state.photo_ids:
            state.photo_ids.append(photo_id)

    def submit_reply(self, state: ConversationState, text: str) -> None:
        """Record a reporter message.

        Usually it answers the pending agent question. If nothing is pending
        it is still kept -- a reporter volunteering "it just moved into the
        water" matters, and the agents read the whole transcript every turn.
        """
        state.add_reporter_message(text)

    # -- The step loop ------------------------------------------------------

    def advance(
        self,
        incident: Incident,
        state: ConversationState,
        images: list[ImageInput] | None = None,
    ) -> TurnResult:
        """Perform the next step and return what to show the reporter.

        Agent steps (identification, assessment) do not return on their own:
        they produce a result and immediately re-decide, so running the model
        and asking the question it chose happen in one request, not two.
        """
        decision = decide_next_step(state)
        logger.debug(
            "Incident %s: %s -- %s", incident.incident_id, decision.action, decision.reason
        )

        if decision.action in self.stop_at:
            return TurnResult(
                message=f"[stopped before {decision.action.value}]",
                complete=True,
                action=decision.action,
                reason=decision.reason,
            )

        match decision.action:
            case StepAction.REQUEST_PHOTO:
                state.stage = ConversationStage.AWAITING_PHOTO
                return _turn(
                    decision,
                    "Please take a photo of the animal from where you are standing. "
                    "Do not get closer to take it.",
                )

            case StepAction.REQUEST_LOCATION:
                state.stage = ConversationStage.AWAITING_LOCATION
                return _turn(
                    decision,
                    "Please share your location so we can check the tide and find "
                    "the nearest rescue team.",
                )

            case StepAction.REQUEST_BETTER_PHOTO:
                state.better_photo_requested = True
                return _turn(
                    decision,
                    f"{decision.reason} Could you send another photo? Please stay "
                    "where you are -- do not move closer to the animal.",
                )

            case StepAction.RUN_IDENTIFICATION:
                try:
                    self._run_identification(incident, state, images)
                except AgentError as exc:
                    return self._ask_reporter_to_retry(incident, exc)
                return self.advance(incident, state, images)

            case StepAction.RUN_ASSESSMENT:
                try:
                    self._run_assessment(incident, state, images)
                except AgentError as exc:
                    return self._ask_reporter_to_retry(incident, exc)
                return self.advance(incident, state, images)

            case StepAction.ASK_CLARIFYING_QUESTION:
                return self._ask_clarifying_question(state, decision)

            case StepAction.FINALISE:
                self._finalise(incident, state)
                return TurnResult(
                    message=self._reporter_closing_message(incident),
                    complete=True,
                    action=decision.action,
                    reason=decision.reason,
                )

        raise RuntimeError(f"Unhandled pipeline action: {decision.action}")

    # -- Steps --------------------------------------------------------------

    def _call_agent(self, agent: Agent, incident: Incident, **kwargs: Any) -> Any:
        """Run one agent and record how the call went on the incident.

        Every model call the pipeline makes goes through here, so the health
        record cannot miss one. Latency, tokens, and attempts land in
        `incident.metrics` whether the call succeeded or not.

        Raises:
            AgentError: Re-raised after being recorded; the caller decides
                what the fail-safe for its step is.
        """
        try:
            result = agent.run(**kwargs)
        except AgentError as exc:
            incident.metrics.update(agent.last_metrics)
            health.record_failure(
                incident.metrics,
                agent=agent.name,
                kind=exc.kind,
                attempts=exc.attempts,
                detail=str(exc),
            )
            raise

        incident.metrics.update(agent.last_metrics)
        health.record_success(
            incident.metrics, attempts=agent.last_metrics.get(f"{agent.name}_attempts") or 1
        )
        return result

    def _ask_reporter_to_retry(self, incident: Incident, error: AgentError) -> TurnResult:
        """Fail-safe for identification and assessment: ask the reporter to try again.

        Nothing is lost: the conversation state is unchanged, so the next
        request (a tap on "Try again", or any new message) re-runs the same
        step. The incident stays open on the responder console, flagged for
        review, so a stalled intake is visible to a coordinator.
        """
        health.set_awaiting_retry(incident.metrics, True)
        logger.error(
            "Incident %s: %s agent failed (%s, %d attempt(s)); reporter asked to retry. %s",
            incident.incident_id,
            error.agent,
            error.kind,
            error.attempts,
            health.summary(incident.metrics),
        )
        self._save(incident)
        return TurnResult(
            message=SERVICE_RETRY_MESSAGE,
            awaiting_reply=True,
            action=StepAction.SERVICE_RETRY,
            reason=f"{error.agent} agent unavailable ({error.kind}).",
        )

    def _ask_clarifying_question(
        self, state: ConversationState, decision: Decision
    ) -> TurnResult:
        """Put an agent's question to the reporter and charge it to a budget."""
        question = decision.question
        assert question is not None

        # Assessment only runs after identification is settled, so whether it
        # has started tells us whose budget this question spends.
        if state.assessment is None:
            state.identification_questions_asked += 1
            agent_name = "identification"
        else:
            state.assessment_questions_asked += 1
            agent_name = "assessment"

        state.add_agent_message(question.question, agent_name=agent_name, question=question)
        return TurnResult(
            message=question.question,
            options=question.options,
            awaiting_reply=True,
            action=StepAction.ASK_CLARIFYING_QUESTION,
            reason=decision.reason,
        )

    def _run_identification(
        self,
        incident: Incident,
        state: ConversationState,
        images: list[ImageInput] | None,
    ) -> None:
        """Call the identification agent and store its result."""
        state.stage = ConversationStage.IDENTIFYING
        incident.status = IncidentStatus.IDENTIFYING

        result = self._call_agent(
            self.identification_agent,
            incident,
            images=images,
            location_summary=self._environment_summary(incident),
            transcript=state.transcript,
            questions_asked=state.identification_questions_asked,
            questions_remaining=max(
                0, settings.max_identification_questions - state.identification_questions_asked
            ),
            previous_candidates=(
                state.identification.candidates if state.identification else None
            ),
            photo_count=max(len(state.photo_ids), 1),
        )

        state.identification = result
        state.identification_stale = False
        incident.identification = result

        # Record why identification stopped, if it has. This is the number the
        # evaluation notebook compares against what the responder found.
        state.identification_stop_reason = identification_stop_reason(state)
        if state.identification_stop_reason:
            incident.metrics["identification_stop_reason"] = state.identification_stop_reason
            incident.metrics["identification_questions_asked"] = (
                state.identification_questions_asked
            )
        self._save(incident)

    def _run_assessment(
        self,
        incident: Incident,
        state: ConversationState,
        images: list[ImageInput] | None,
    ) -> None:
        """Call the assessment agent, then score severity deterministically."""
        state.stage = ConversationStage.ASSESSING
        incident.status = IncidentStatus.ASSESSING

        result = self._call_agent(
            self.assessment_agent,
            incident,
            images=images,
            identification=state.identification,
            context=incident.environment,
            environment_summary=self._environment_summary(incident),
            transcript=state.transcript,
            questions_asked=state.assessment_questions_asked,
            questions_remaining=max(
                0, settings.max_assessment_questions - state.assessment_questions_asked
            ),
        )

        # --- Severity: computed here, not by the model. See dispatch/severity.py.
        severity = score_severity(
            injury=result.injury,
            hazards=result.hazards,
            animal_group=state.identification.animal_group,
            context=incident.environment,
            # Ran out of questions while still unsure: the flags may be missing
            # things, so triage confidence is reduced.
            data_quality_incomplete=(
                not result.is_confident
                and state.assessment_questions_asked >= settings.max_assessment_questions
            ),
            needs_review=not state.identification.is_confident,
        )
        result.severity_level = severity.level
        result.severity_score = severity.score
        result.severity_confidence = severity.confidence
        result.animal_group = state.identification.animal_group

        policy = recommended_action(severity.level)
        result.requires_human_review = policy["coordinator_review_required"]
        if not result.recommended_action:
            result.recommended_action = policy["recommended_action"]

        state.assessment = result
        state.assessment_stale = False
        incident.assessment = result
        incident.metrics["severity_reasons"] = severity.reasons
        incident.metrics["severity_triggered_rules"] = severity.triggered_rules
        incident.metrics["severity_contributions"] = severity.contributions
        self._save(incident)

    def _finalise(self, incident: Incident, state: ConversationState) -> None:
        """Write the report, check it, detect duplicates, and rank responders."""
        state.stage = ConversationStage.COMPLETE
        assert incident.assessment is not None and incident.identification is not None
        environment_summary = self._environment_summary(incident)

        # --- 1. Write the report ---
        report: IncidentReport | None
        try:
            report = self._call_agent(
                self.report_agent,
                incident,
                identification=incident.identification,
                assessment=incident.assessment,
                context=incident.environment,
                environment_summary=environment_summary,
                transcript=state.transcript,
                severity_reasons=incident.metrics.get("severity_reasons", []),
            )
        except AgentError as exc:
            # Fail-safe: no written report, but the incident still reaches a
            # coordinator with the assessment findings, severity, and the
            # transcript. Losing the prose must not lose the emergency.
            report = None
            health.record_fallback(incident.metrics, health.FALLBACK_REPORT_UNAVAILABLE)
            incident.assessment.requires_human_review = True
            logger.error(
                "Incident %s: report could not be written (%s); sending to "
                "coordinators without one, held for review.",
                incident.incident_id,
                exc.kind,
            )
        incident.report = report

        # --- 2. Check it before anyone sees it ---
        if report is not None:
            verdict = self.review_report(incident, report, environment_summary)
            incident.metrics["guardrail"] = verdict.model_dump(mode="json")
            if not verdict.approved:
                # Held, not discarded: a guardrail false positive must not bury
                # a real emergency. A coordinator reads it alongside the findings.
                incident.assessment.requires_human_review = True
                logger.warning(
                    "Incident %s held for review: grounded=%s safe=%s",
                    incident.incident_id,
                    verdict.is_grounded,
                    verdict.is_safe,
                )

        # --- 3. Duplicate detection (needs the database) ---
        if self.session is not None and incident.location:
            candidates = repository.find_duplicate_candidates(
                self.session,
                incident_id=incident.incident_id,
                latitude=incident.location.latitude,
                longitude=incident.location.longitude,
            )
            match = find_duplicate(
                latitude=incident.location.latitude,
                longitude=incident.location.longitude,
                reported_at=incident.created_at,
                animal_group=incident.identification.animal_group,
                candidates=candidates,
            )
            if match:
                incident.metrics["duplicate_match"] = match.model_dump(mode="json")
                if is_probable_duplicate(match):
                    incident.duplicate_of = match.incident_id

        # --- 4. Rank responders ---
        # Skipped for a healthy animal: offering a team invites a needless dispatch.
        if incident.assessment.severity_level is SeverityLevel.GUIDANCE:
            incident.status = IncidentStatus.GUIDANCE_ONLY
        else:
            incident.dispatch_candidates = self.rank_responders(incident)
            incident.status = (
                IncidentStatus.CANCELLED
                if incident.duplicate_of
                else IncidentStatus.AWAITING_DISPATCH
            )

        health.log_summary(incident.incident_id, incident.metrics)
        self._save(incident)
        if self.session is not None:
            repository.save_messages(self.session, incident.incident_id, state.transcript)

    # -- Public helpers (also used by the notebooks) --------------------------

    def review_report(
        self, incident: Incident, report: IncidentReport, environment_summary: str
    ) -> GuardrailVerdict:
        """Run the guardrail check, failing *closed* to human review on error.

        An exception here must not block a real emergency, so a failed check is
        recorded as "not verified" and the incident is held for a human -- the
        same outcome as a check that found problems. The verdict is marked
        `check_failed` and the incident's health record notes the fail-safe, so
        "the check found a problem" and "the check could not run" stay
        distinguishable (which matters when measuring guardrail false positives).
        """
        try:
            return self._call_agent(
                self.guardrail_agent,
                incident,
                report=report,
                assessment=incident.assessment,
                environment_summary=environment_summary,
                species=incident.identification.display_name
                if incident.identification
                else "unidentified animal",
                identification_summary=describe_resolution(
                    incident.identification.resolution if incident.identification else None
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Guardrail check failed for %s: %s", incident.incident_id, exc)
            if not isinstance(exc, AgentError):
                # `_call_agent` records model failures; this is anything else
                # (a prompt that would not render, say). Record it too.
                health.record_failure(
                    incident.metrics,
                    agent=self.guardrail_agent.name,
                    kind="internal_error",
                    attempts=1,
                    detail=str(exc),
                )
            health.record_fallback(incident.metrics, health.FALLBACK_GUARDRAIL_CHECK_FAILED)
            return GuardrailVerdict(
                is_grounded=False,
                is_safe=False,
                check_failed=True,
                notes=f"Guardrail check could not be completed: {exc}",
            )

    def rank_responders(self, incident: Incident) -> list[DispatchCandidate]:
        """Rank rescue organisations for this incident."""
        assert incident.assessment is not None

        area_terms: list[str] = []
        if incident.location:
            place = reverse_geocode(
                round(incident.location.latitude, 5), round(incident.location.longitude, 5)
            )
            if place:
                area_terms = place.area_terms

        return rank_centers(
            area_terms=area_terms,
            animal_group=incident.identification.animal_group
            if incident.identification
            else incident.assessment.animal_group,
            injury=incident.assessment.injury,
            latitude=incident.location.latitude if incident.location else None,
            longitude=incident.location.longitude if incident.location else None,
        )

    # -- Internals ------------------------------------------------------------

    def _save(self, incident: Incident) -> None:
        """Persist the incident, or do nothing when running in memory."""
        if self.session is not None:
            repository.save_incident(self.session, incident)

    @staticmethod
    def _environment_summary(incident: Incident) -> str:
        if incident.environment is None:
            return "Location and environmental data unavailable."
        return summarise_for_prompt(incident.environment)

    @staticmethod
    def _reporter_closing_message(incident: Incident) -> str:
        """What the reporter sees when intake finishes.

        Never promises a response or an arrival time: no coordinator has
        approved anything yet, and an unmet promise is worse than none.
        """
        assessment = incident.assessment
        if assessment is None:
            return "Thank you. Your report has been received."

        lines = [assessment.safety_guidance] if assessment.safety_guidance else []
        if assessment.reporter_instructions:
            lines.append("What you can do now:")
            lines.extend(f"• {step}" for step in assessment.reporter_instructions)

        if incident.status is IncidentStatus.GUIDANCE_ONLY:
            lines.append(
                "Based on what you have described, this animal does not appear to "
                "need rescue. Please keep your distance and let it be."
            )
        elif incident.duplicate_of:
            lines.append(
                "Someone has already reported this animal, so a team is aware of it. "
                "Thank you for checking."
            )
        else:
            lines.append(
                "Your report has been sent to the rescue coordinators for this area. "
                "You can follow its progress on the map."
            )
        return "\n".join(lines)


def _turn(decision: Decision, message: str) -> TurnResult:
    """A reporter-facing prompt that waits for them to act."""
    return TurnResult(
        message=message,
        awaiting_reply=True,
        action=decision.action,
        reason=decision.reason,
    )
