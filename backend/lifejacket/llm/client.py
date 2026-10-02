"""The one place LifeJacket talks to a language model.

Every agent goes through `LLMClient`. Centralising it buys us three things the
prototypes lacked:

1. **Structured output.** We use Gemini's JSON mode (`response_mime_type` plus a
   schema) rather than asking for JSON in prose and slicing braces out of the
   reply. The model is constrained to valid JSON by the decoder, so the
   brace-slicing failure mode disappears.
2. **Retries.** Network blips and occasional schema violations are retried with
   exponential backoff. The prototype had none, so one bad reply ended the
   conversation.
3. **Telemetry.** Token counts and latency are recorded per call, which is how
   we answer "what does one incident cost?".

Auth uses Application Default Credentials (ADC) -- there is no API key or key
file anywhere in this codebase. Each developer logs in once with their own
Google account, which must have been granted access to the
`spring-2026-lifejacket` GCP project:

    gcloud auth application-default login

That stores a credential under ~/.config/gcloud/ (outside this repo, outside
iCloud Drive) and every terminal, notebook, and the API server picks it up
automatically. Nothing in this file needs to change -- the SDK call below
finds the credential on its own.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from lifejacket.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """A parsed model reply plus the metadata we need for evaluation."""

    data: dict[str, Any]
    raw_text: str
    model: str
    latency_seconds: float
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    attempts: int = 1


@dataclass
class ImageInput:
    """One photo to send alongside the prompt."""

    data: bytes
    mime_type: str = "image/jpeg"


class LLMError(RuntimeError):
    """Raised when the model could not be reached or produced unusable output."""


@dataclass
class LLMClient:
    """Thin wrapper over the Google Gen AI SDK, pointed at Vertex AI.

    One client is shared by all agents. Construct it once at app startup
    (`api.main`) or call `get_client()` for the lazy singleton.
    """

    model: str = field(default_factory=lambda: settings.llm_model)
    project: str = field(default_factory=lambda: settings.gcp_project)
    location: str = field(default_factory=lambda: settings.gcp_location)
    temperature: float = field(default_factory=lambda: settings.llm_temperature)
    max_retries: int = field(default_factory=lambda: settings.llm_max_retries)

    _client: Any = field(default=None, init=False, repr=False)

    def _ensure_client(self) -> Any:
        """Create the SDK client on first use.

        Deferred so that importing this module (for tests, or for the type
        hints) does not require credentials to be present.
        """
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:  # pragma: no cover
                raise LLMError(
                    "google-genai is not installed. "
                    "Run: pip install -r backend/requirements.txt"
                ) from exc

            self._client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
        return self._client

    def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        images: list[ImageInput] | None = None,
        temperature: float | None = None,
        system_instruction: str | None = None,
    ) -> LLMResponse:
        """Send a prompt (and optional photos) and get back validated JSON.

        Args:
            prompt: The fully-rendered prompt text.
            schema: JSON Schema the reply must conform to. Build these with
                `lifejacket.llm.schema.object_schema` so they stay consistent.
            images: Photos to include. Gemini reads these natively.
            temperature: Overrides the default for this call. Identification
                uses a low value for reproducibility; report writing can be
                slightly higher for readable prose.
            system_instruction: Standing instructions (safety boundaries) that
                apply regardless of the task. See `prompts/system_principles.md`.

        Returns:
            An `LLMResponse` whose `.data` is the parsed object.

        Raises:
            LLMError: After `max_retries` failed attempts.
        """
        client = self._ensure_client()
        contents = self._build_contents(prompt, images or [])

        config: dict[str, Any] = {
            "temperature": self.temperature if temperature is None else temperature,
            "max_output_tokens": settings.llm_max_output_tokens,
            "response_mime_type": "application/json",
            "response_json_schema": schema,
            # Bounds how much of max_output_tokens "thinking" can consume
            # before the model has to write the actual JSON. Without this,
            # thinking length varies call to call and can truncate the JSON
            # mid-string -- see the comment on llm_thinking_budget.
            "thinking_config": {"thinking_budget": settings.llm_thinking_budget},
        }
        if system_instruction:
            config["system_instruction"] = system_instruction

        last_error: Exception | None = None
        started = time.monotonic()

        for attempt in range(1, self.max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                text = (response.text or "").strip()
                if not text:
                    raise LLMError("Model returned an empty response")

                data = json.loads(text)
                if not isinstance(data, dict):
                    raise LLMError(f"Expected a JSON object, got {type(data).__name__}")

                prompt_tokens, output_tokens = _read_usage(response)
                return LLMResponse(
                    data=data,
                    raw_text=text,
                    model=self.model,
                    latency_seconds=time.monotonic() - started,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    attempts=attempt,
                )

            except Exception as exc:  # noqa: BLE001 - deliberately broad
                # Transport errors, quota errors, and malformed JSON all get the
                # same treatment: wait and try again. Distinguishing them adds
                # branching without changing what we would do about it.
                last_error = exc
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s", attempt, self.max_retries, exc
                )
                if attempt < self.max_retries:
                    # Exponential backoff with jitter, so concurrent intake
                    # sessions do not retry in lockstep.
                    time.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.5))

        raise LLMError(
            f"LLM call failed after {self.max_retries} attempts: {last_error}"
        ) from last_error

    @staticmethod
    def _build_contents(prompt: str, images: list[ImageInput]) -> list[Any]:
        """Interleave photos and prompt text into the SDK's content format.

        Images go first: Gemini attends to the question better when it has
        already seen what the question is about.
        """
        from google.genai import types

        parts: list[Any] = [
            types.Part.from_bytes(data=img.data, mime_type=img.mime_type) for img in images
        ]
        parts.append(types.Part.from_text(text=prompt))
        return [types.Content(role="user", parts=parts)]


def _read_usage(response: Any) -> tuple[int | None, int | None]:
    """Pull token counts off a response, tolerating SDK shape changes."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None, None
    return (
        getattr(usage, "prompt_token_count", None),
        getattr(usage, "candidates_token_count", None),
    )


_client_singleton: LLMClient | None = None


def get_client() -> LLMClient:
    """Return the shared client, creating it on first call."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LLMClient()
    return _client_singleton
