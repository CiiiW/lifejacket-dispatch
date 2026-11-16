"""YOLO handoff contract, independent of weights and transport.

This validates detector OUTPUT only. It does not authorize attachment to a case,
verify the source image, select the target animal or infer injury/urgency.
"""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DetectorBox(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    class_name: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    xyxy: tuple[float, float, float, float]
    track_id: str | None = Field(default=None, max_length=64)


class DetectorFrameResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal[1] = 1
    evidence_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    model_name: str = Field(min_length=1, max_length=120)
    model_version: str = Field(min_length=1, max_length=120)
    weights_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_kind: Literal["sample_footage", "operator_capture"]
    status: Literal["completed", "failed"]
    detections: list[DetectorBox] = Field(default_factory=list, max_length=32)
    error_code: Literal["decode_failed", "inference_failed", "model_unavailable"] | None = None

    @model_validator(mode="after")
    def validate_result(self):
        if self.status == "failed":
            if self.detections or self.error_code is None:
                raise ValueError("Failed inference requires an error code and no detections")
        elif self.error_code is not None:
            raise ValueError("Completed inference cannot carry an error code")
        for detection in self.detections:
            x1, y1, x2, y2 = detection.xyxy
            if not all(math.isfinite(v) for v in detection.xyxy):
                raise ValueError("Coordinates must be finite")
            if not (0 <= x1 < x2 <= self.width and 0 <= y1 < y2 <= self.height):
                raise ValueError("Box must be nonempty and inside the source image")
        return self

    def agent_detections(self):
        """Map pixel XYXY into our existing normalized YXYX convention.

        Confidence and track IDs remain detector metadata, not identity or health
        facts. Do not silently clamp malformed boxes into apparently valid ones.
        """
        if self.status != "completed":
            raise ValueError("Failed inference must not be represented as no animals")
        result = []
        for detection in self.detections:
            x1, y1, x2, y2 = detection.xyxy
            box = [
                round(y1 / self.height * 1000),
                round(x1 / self.width * 1000),
                round(y2 / self.height * 1000),
                round(x2 / self.width * 1000),
            ]
            if box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("Box too small for normalized coordinates; review manually")
            result.append({"box": box, "description": detection.class_name, "kind": "other"})
        return result
