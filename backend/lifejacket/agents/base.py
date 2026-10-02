"""Shared machinery for the LLM agents.

Each agent follows the same three steps:

1. **Render** a prompt from a file in `prompts/`, with the current state
   substituted in.
2. **Call** the model with a JSON schema constraining the reply.
3. **Validate** that reply into a Pydantic model from `models.schemas`.

`Agent` implements the loop; subclasses supply the prompt path, the schema, and
the result type. Keeping this common means a new agent is about thirty lines,
and every agent gets retries, telemetry, and the system safety principles for
free.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from lifejacket.llm.client import ImageInput, LLMClient, LLMError, get_client
from lifejacket.llm.prompts import render_prompt, system_principles

logger = logging.getLogger(__name__)

ResultT = TypeVar("ResultT", bound=BaseModel)


class AgentError(RuntimeError):
    """Raised when an agent could not produce a usable result."""


class Agent(ABC, Generic[ResultT]):
    """Base class for a single-call LLM agent.

    Subclasses define:
        name: For logging and transcript attribution.
        prompt_path: Relative to `prompts/`.
        result_type: The Pydantic model to validate into.
        output_schema: The JSON Schema sent to the model.
    """

    name: str
    prompt_path: str
    result_type: type[ResultT]
    #: Report writing benefits from slightly more freedom than classification.
    temperature: float | None = None

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_client()
        #: Populated after each run, for the incident's `metrics` bag.
        self.last_metrics: dict[str, Any] = {}
        #: The exact prompt sent and the raw JSON received on the last run.
        #: Kept for the notebooks, where seeing what the model was actually
        #: told is the fastest way to debug a bad answer.
        self.last_prompt: str | None = None
        self.last_response: dict[str, Any] | None = None

    @property
    @abstractmethod
    def output_schema(self) -> dict[str, Any]:
        """The JSON Schema the model's reply must satisfy."""

    @abstractmethod
    def build_prompt_values(self, **kwargs: Any) -> dict[str, Any]:
        """Map the caller's arguments to the prompt's `{placeholders}`."""

    def parse(self, data: dict[str, Any]) -> ResultT:
        """Validate the model's JSON into the result type.

        Overridden by agents whose JSON shape differs from their Pydantic model
        (identification does, because it flattens a nested question object).
        """
        return self.result_type.model_validate(data)

    def run(self, images: list[ImageInput] | None = None, **kwargs: Any) -> ResultT:
        """Render, call, and validate.

        Raises:
            AgentError: If the model could not be reached, or returned JSON
                that does not satisfy the result type.
        """
        prompt = render_prompt(self.prompt_path, **self.build_prompt_values(**kwargs))
        self.last_prompt = prompt

        try:
            response = self.client.generate_json(
                prompt=prompt,
                schema=self.output_schema,
                images=images,
                temperature=self.temperature,
                system_instruction=system_principles(),
            )
        except LLMError as exc:
            raise AgentError(f"{self.name}: model call failed: {exc}") from exc

        self.last_response = response.data
        self.last_metrics = {
            f"{self.name}_latency_seconds": round(response.latency_seconds, 2),
            f"{self.name}_prompt_tokens": response.prompt_tokens,
            f"{self.name}_output_tokens": response.output_tokens,
            f"{self.name}_attempts": response.attempts,
        }

        try:
            return self.parse(response.data)
        except ValidationError as exc:
            # The schema constrained the shape, so this means our Pydantic
            # model and our JSON Schema have drifted apart -- a bug in our
            # code, not a model failure. Log the payload to make it findable.
            logger.error("%s returned unparseable data: %s", self.name, response.raw_text)
            raise AgentError(f"{self.name}: could not parse model output: {exc}") from exc
