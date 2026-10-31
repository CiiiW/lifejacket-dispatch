"""Demo evidence is a separate contract, never a real observation or incident."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from lifejacket.models.schemas import DetectionResult


class DemoContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class DemoFrameMetadata(DemoContract):
    evidence_kind: Literal["toy_demo", "synthetic_test"]
    source: str = Field(min_length=1, max_length=500)
    rights_note: str = Field(min_length=1, max_length=1000)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    offset_seconds: float = Field(ge=0, le=600)
    captured_at: AwareDatetime | None = None
    # No unvalidated GPS attachment; telemetry alignment is a later milestone.
    detection: DetectionResult | None = None
    detection_status: Literal["not_run", "completed", "failed"] = "not_run"
    detector_model: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def detection_consistent(self):
        if (self.detection_status == "completed") != (self.detection is not None):
            raise ValueError("Only completed detection may contain candidates")
        return self


class DemoReview(DemoContract):
    expected_revision: int = Field(ge=0)
    actor: str = Field(min_length=1, max_length=80)
    decision: Literal["kept", "rejected"]
    note: str = Field(min_length=1, max_length=1000)
