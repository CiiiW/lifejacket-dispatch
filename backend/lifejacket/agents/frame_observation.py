"""Frame observation: describe one video frame so Python can choose evidence frames.

The model only *observes* (is an animal visible, what kind of shot, how clear,
anything notable). Choosing which frames to keep is deterministic code in
`drones/frame_select.py`, so the choice can be tested and explained.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lifejacket.agents.base import Agent
from lifejacket.llm.schema import BOOLEAN, STRING, enum_of, object_schema

VIEWS = ("wide_context", "full_body", "head_face", "body_detail", "other")
SIDES = ("top_down", "left", "right", "front", "rear", "unknown")

_SCORE = {"type": "integer", "minimum": 1, "maximum": 5}

FRAME_OBSERVATION_SCHEMA = object_schema(
    {
        "animal_visible": BOOLEAN,
        "view": enum_of(*VIEWS),
        "side": enum_of(*SIDES),
        "clarity": _SCORE,
        "animal_size": _SCORE,
        "environment": STRING,
        "notable": STRING,
        "notable_clear": BOOLEAN,
    }
)


class FrameObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    animal_visible: bool
    view: Literal["wide_context", "full_body", "head_face", "body_detail", "other"]
    side: Literal["top_down", "left", "right", "front", "rear", "unknown"]
    clarity: int = Field(ge=1, le=5)
    animal_size: int = Field(ge=1, le=5)
    environment: str = Field(max_length=200)
    notable: str = Field(max_length=400)
    notable_clear: bool


class FrameObservationAgent(Agent[FrameObservation]):
    """Describes a single frame. One call per candidate frame."""

    name = "frame_observation"
    prompt_path = "drones/observe_frame.md"
    result_type = FrameObservation
    # The same frame should be described the same way on a re-run.
    temperature = 0.1

    @property
    def output_schema(self) -> dict[str, Any]:
        return FRAME_OBSERVATION_SCHEMA

    def build_prompt_values(self, **kwargs: Any) -> dict[str, Any]:
        return {}
