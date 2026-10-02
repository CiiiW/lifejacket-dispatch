"""Talk to the chatbots from a Jupyter notebook.

A thin wrapper around `services.pipeline.IntakePipeline` -- the *same* code the
API runs -- with three conveniences for experimenting:

- **No database.** Everything lives in memory; nothing is saved.
- **One chatbot at a time.** `identification_only` stops before assessment;
  `assessment_only` skips identification by assuming a species you choose.
- **Readable output.** Every turn prints the question, the tap-able options,
  and *why* the system chose to ask it. `show_*` methods print the agents'
  structured results, and `last_prompt()` shows exactly what the model was sent.

Usage:

    from lifejacket.chatbot.playground import ChatPlayground

    chat = ChatPlayground.identification_only(
        photos=["my_seal.jpg"], latitude=36.8044, longitude=-121.7869
    )
    chat.answer("shorter")
    chat.show_identification()

Pass `client=ScriptedLLMClient.scenario("dolphin")` to run offline, without
GCP credentials.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from lifejacket.chatbot.session import ConversationState, StepAction
from lifejacket.config import settings
from lifejacket.context.environment import summarise_for_prompt
from lifejacket.llm.client import ImageInput, LLMClient
from lifejacket.models.schemas import (
    AnimalGroup,
    ChatRole,
    EnvironmentalContext,
    GeoPoint,
    IdentificationResult,
    IncidentReport,
    SpeciesCandidate,
)
from lifejacket.services.pipeline import IntakePipeline, TurnResult
from lifejacket.taxonomy import describe_resolution, resolve_taxon

_RULE = "-" * 72


class ChatPlayground:
    """One in-memory conversation with the LifeJacket chatbots.

    Build one with `full`, `identification_only`, or `assessment_only`.
    """

    def __init__(
        self,
        *,
        photos: list[str | Path] | None = None,
        latitude: float = 36.8044,
        longitude: float = -121.7869,
        place_name: str | None = None,
        client: LLMClient | None = None,
        stop_at: set[StepAction] | None = None,
        live_context: bool = True,
        verbose: bool = True,
    ) -> None:
        """
        Args:
            photos: Paths to image files. May be empty when using a scripted
                client, which ignores images.
            latitude, longitude: Where the animal is. Defaults to Moss Landing.
            place_name: Optional label; otherwise resolved by reverse geocoding.
            client: LLM client. Defaults to the real Vertex client.
            stop_at: Pipeline steps to halt before.
            live_context: Fetch real tide/weather/place data. Set False to skip
                the network calls (about a second) and run fully offline.
            verbose: Print each turn as it happens.
        """
        self.client = client
        self.verbose = verbose
        self.pipeline = IntakePipeline(session=None, client=client, stop_at=stop_at)
        self.images = [_load_image(p) for p in (photos or [])]

        self.incident, self.state = self.pipeline.start_incident()
        self.last_turn: TurnResult | None = None

        # Photo first, then location -- the same order the phone app uses.
        photo_ids = [f"PHOTO_{i}" for i in range(len(self.images))] or ["PHOTO_none"]
        for photo_id in photo_ids:
            self.pipeline.attach_photo(self.state, photo_id)

        location = GeoPoint(latitude=latitude, longitude=longitude, place_name=place_name)
        if live_context:
            self.pipeline.set_location(self.incident, self.state, location)
        else:
            self.state.has_location = True
            self.incident.location = location
            self.incident.environment = EnvironmentalContext(
                location=location, unavailable=["weather", "tide", "place_name"]
            )

    # -- Constructors ---------------------------------------------------------

    @classmethod
    def full(cls, **kwargs) -> ChatPlayground:
        """Run every agent: identification, assessment, report, guardrail."""
        chat = cls(**kwargs)
        chat._advance()
        return chat

    @classmethod
    def identification_only(cls, **kwargs) -> ChatPlayground:
        """Run only the identification chatbot; stop before assessment."""
        chat = cls(stop_at={StepAction.RUN_ASSESSMENT}, **kwargs)
        chat._advance()
        return chat

    @classmethod
    def identification_and_assessment(cls, **kwargs) -> ChatPlayground:
        """Run identification for real, then assessment; stop before the report.

        Unlike `assessment_only`, nothing is assumed: the species comes from
        the photo, exactly as `full` does, just stopping one step earlier.
        This is what notebook 04 uses so you never have to copy a species
        name out of notebook 03 by hand -- the same photo just keeps going.
        """
        chat = cls(stop_at={StepAction.FINALISE}, **kwargs)
        chat._advance()
        return chat

    @classmethod
    def assessment_only(
        cls,
        *,
        species: str = "Harbor seal",
        scientific_name: str = "Phoca vitulina",
        animal_group: str = "pinniped",
        family: str | None = "Phocidae",
        confidence: float = 0.95,
        **kwargs,
    ) -> ChatPlayground:
        """Skip identification by assuming a species; stop before the report.

        Lets you test how the assessment chatbot handles a given animal
        without first talking your way through identification.
        """
        chat = cls(stop_at={StepAction.FINALISE}, **kwargs)
        candidate = SpeciesCandidate(
            common_name=species,
            scientific_name=scientific_name,
            confidence=confidence,
            animal_group=AnimalGroup(animal_group),
            family=family,
        )
        identification = IdentificationResult(
            candidates=[candidate],
            resolution=resolve_taxon(
                [candidate], settings.identification_confidence_threshold
            ),
            # Nothing left to ask: we are telling the system what it is.
            species_distinguishable=False,
        )
        chat.state.identification = identification
        chat.incident.identification = identification
        chat._advance()
        return chat

    # -- Conversation ---------------------------------------------------------

    def answer(self, text: str) -> TurnResult:
        """Reply to the current question, as the reporter would."""
        if self.done:
            print("(this conversation has finished -- build a new ChatPlayground,")
            print(" or call .finish() if it was stopped before the report)")
            return self.last_turn
        if self.verbose:
            print(f"YOU:   {text}")
        self.pipeline.submit_reply(self.state, text)
        return self._advance()

    def interactive(self) -> None:
        """Type answers in a loop until the conversation ends. Enter q to quit.

        In Jupyter an input box appears under the cell. Tapping an option on
        the phone sends its text, so typing the option text is equivalent.
        """
        while not self.done:
            text = input("YOU: ").strip()
            if text.lower() in {"q", "quit", "exit"}:
                print("(stopped -- call .answer(...) or .interactive() to continue)")
                return
            if text:
                self.answer(text)

    def finish(self) -> TurnResult:
        """Remove any stop and run the remaining steps (report, guardrail)."""
        self.pipeline.stop_at = set()
        return self._advance()

    @property
    def done(self) -> bool:
        return bool(self.last_turn and self.last_turn.complete)

    def _advance(self) -> TurnResult:
        turn = self.pipeline.advance(self.incident, self.state, self.images)
        self.last_turn = turn
        if self.verbose:
            _print_turn(turn, self.state)
        return turn

    # -- Inspection -----------------------------------------------------------

    def show_identification(self) -> None:
        """Print the candidates, the resolved taxon, and why it stopped."""
        result = self.state.identification
        print(_RULE)
        print("IDENTIFICATION")
        print(_RULE)
        if result is None:
            print("(not run yet)")
            return

        print(f"{'species':<28}{'genus':<14}{'family':<16}{'prob':>6}")
        for c in sorted(result.candidates, key=lambda c: c.confidence, reverse=True):
            print(
                f"{c.common_name:<28}{(c.genus or '-'):<14}"
                f"{(c.family or '-'):<16}{c.confidence:>6.2f}"
            )
        print()
        print("Resolved as :", describe_resolution(result.resolution))
        print("Group       :", result.animal_group.value, "(this is what routes dispatch)")
        print(
            "Questions   :",
            f"{self.state.identification_questions_asked} of "
            f"{settings.max_identification_questions} used",
        )
        if self.state.identification_stop_reason:
            print("Stopped     :", self.state.identification_stop_reason)
        if result.reasoning:
            print("Reasoning   :", result.reasoning)

    def show_assessment(self) -> None:
        """Print the condition flags and the deterministic severity result."""
        result = self.state.assessment
        print(_RULE)
        print("ASSESSMENT")
        print(_RULE)
        if result is None:
            print("(not run yet)")
            return

        flags = result.injury.model_dump()
        flags.update(result.hazards.model_dump())
        positive = [k for k, v in flags.items() if v is True]
        print("Flags set   :", ", ".join(positive) or "(none)")
        print("Mobility    :", result.injury.mobility_concern.value)
        print("Summary     :", result.injury.summary or "-")
        print()
        print(
            f"SEVERITY    : {result.severity_level.value.upper()}  "
            f"(score {result.severity_score}, confidence {result.severity_confidence})"
        )
        contributions = self.incident.metrics.get("severity_contributions", {})
        for flag, points in contributions.items():
            print(f"   +{points:<4} {flag}")
        for reason in self.incident.metrics.get("severity_reasons", []):
            print(f"   - {reason}")
        print()
        print("Action      :", result.recommended_action)
        for step in result.reporter_instructions:
            print("   *", step)
        print(
            "Questions   :",
            f"{self.state.assessment_questions_asked} of "
            f"{settings.max_assessment_questions} used",
        )

    def show_report(self) -> None:
        """Print the responder report, guardrail verdict, and ranked responders."""
        report = self.incident.report
        print(_RULE)
        print("INCIDENT REPORT")
        print(_RULE)
        if report is None:
            print("(not written yet -- call .finish())")
            return
        print(_format_report(report))

        verdict = self.incident.metrics.get("guardrail")
        if verdict:
            print()
            approved = verdict["is_grounded"] and verdict["is_safe"]
            print("GUARDRAIL   :", "approved" if approved else "HELD FOR HUMAN REVIEW")
            for key in ("unsupported_claims", "unsafe_advice", "missing_critical_content"):
                for item in verdict.get(key) or []:
                    print(f"   {key}: {item}")

        if self.incident.dispatch_candidates:
            print()
            print("SUGGESTED RESPONDERS (coordinator approves)")
            for c in self.incident.dispatch_candidates:
                print(f"   {c.score:.2f}  {c.name}")

    def check_report(self, report: IncidentReport) -> None:
        """Run the guardrail on a report you wrote, against this incident's data.

        Use it to probe the guardrail: write a report with an invented fact or
        unsafe advice, and see whether it is caught.
        """
        verdict = self.pipeline.review_report(
            self.incident, report, self.environment_summary()
        )
        print("grounded:", verdict.is_grounded, "| safe:", verdict.is_safe)
        for item in verdict.unsupported_claims:
            print("  unsupported:", item)
        for item in verdict.unsafe_advice:
            print("  unsafe     :", item)
        for item in verdict.missing_critical_content:
            print("  missing    :", item)

    def transcript(self) -> None:
        """Print the whole conversation."""
        for message in self.state.transcript:
            who = "AGENT" if message.role is ChatRole.AGENT else "YOU"
            print(f"{who:<6} {message.content}")

    def environment_summary(self) -> str:
        """The tide/weather/place text the agents read."""
        if self.incident.environment is None:
            return "No environmental data."
        return summarise_for_prompt(self.incident.environment)

    def last_prompt(self, agent: str = "identification") -> str:
        """The exact prompt last sent to an agent.

        agent: "identification", "assessment", "report", or "guardrail".
        """
        return self._agent(agent).last_prompt or f"(the {agent} agent has not run yet)"

    def last_response(self, agent: str = "identification") -> dict | None:
        """The raw JSON the agent last returned, before any processing."""
        return self._agent(agent).last_response

    def _agent(self, name: str):
        agents = {
            "identification": self.pipeline.identification_agent,
            "assessment": self.pipeline.assessment_agent,
            "report": self.pipeline.report_agent,
            "guardrail": self.pipeline.guardrail_agent,
        }
        if name not in agents:
            raise KeyError(f"Unknown agent '{name}'. Choose from: {', '.join(agents)}")
        return agents[name]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_image(path: str | Path) -> ImageInput:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No photo at {path.resolve()}")
    mime, _ = mimetypes.guess_type(path.name)
    return ImageInput(data=path.read_bytes(), mime_type=mime or "image/jpeg")


def _print_turn(turn: TurnResult, state: ConversationState) -> None:
    if turn.action is StepAction.ASK_CLARIFYING_QUESTION:
        print(f"AGENT: {turn.message}")
        if turn.options:
            print("       options: " + " | ".join(turn.options))
        print(f"       ({turn.reason})")
    elif turn.complete:
        if turn.message and not turn.message.startswith("[stopped"):
            print("AGENT: " + turn.message.replace("\n", "\n       "))
        print(f"-- done: {turn.reason}")
        stop_reason = state.identification_stop_reason
        if stop_reason and stop_reason != turn.reason:
            print(f"-- identification: {stop_reason}")
    elif turn.message:
        print(f"AGENT: {turn.message}")
        print(f"       ({turn.reason})")
    print()


def _format_report(report: IncidentReport) -> str:
    lines = [report.headline, "", report.summary, "", "Actions:"]
    lines += [f"  {i}. {a}" for i, a in enumerate(report.recommended_actions, 1)]
    for title, items in (
        ("Equipment", report.equipment_suggestions),
        ("Hazards", report.hazard_warnings),
        ("Not established", report.unknowns),
    ):
        if items:
            lines += ["", f"{title}:"] + [f"  - {i}" for i in items]
    return "\n".join(lines)
