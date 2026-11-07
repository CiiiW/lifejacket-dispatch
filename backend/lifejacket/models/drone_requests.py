"""Case-linked observation requests; footage never establishes a diagnosis."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from lifejacket.models.drone_intake import Contract


class CreateRequest(Contract):
    suggestion_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    purpose: Literal["verification", "monitoring"]
    objective: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=2000)
    execution_kind: Literal["recorded_demo", "operator_flight"]
    next_review_at: AwareDatetime | None = None
    escalation_criteria: str = Field(min_length=1, max_length=1000)
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @model_validator(mode="after")
    def monitoring_time(self):
        if self.purpose == "monitoring" and self.next_review_at is None:
            raise ValueError("Monitoring requires a next review time")
        if self.next_review_at and self.next_review_at <= datetime.now(UTC):
            raise ValueError("Choose a future monitoring review time")
        return self


class ChangeRequest(Contract):
    revision: int = Field(ge=0)
    status: Literal[
        "approved",
        "in_progress",
        "evidence_ready",
        "reviewed",
        "declined",
        "cancelled",
        "failed",
    ]
    confirmed: Literal[True]
    note: str = Field(min_length=1, max_length=2000)
    operator: str | None = Field(default=None, min_length=1, max_length=120)
    feasibility_confirmed: bool = False
    outcome: Literal["answered", "still_uncertain", "escalation_needed"] | None = None
    next_review_at: AwareDatetime | None = None


class EvidenceMetadata(Contract):
    revision: int = Field(ge=0)
    source_kind: Literal["sample_footage", "operator_capture"]
    source_url: str | None = Field(default=None, max_length=2000)
    rights_note: str = Field(min_length=1, max_length=1000)
    description: str = Field(min_length=1, max_length=2000)
    captured_at: AwareDatetime | None = None
    frame_offset_seconds: float | None = Field(default=None, ge=0)
    # These are animal coordinates, never silently aircraft coordinates.
    animal_latitude: float | None = Field(default=None, ge=-90, le=90)
    animal_longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def provenance(self):
        from urllib.parse import urlsplit

        if self.source_kind == "sample_footage":
            value = urlsplit(self.source_url or "")
            if (
                value.scheme != "https"
                or not value.hostname
                or value.username
                or value.password
            ):
                raise ValueError("Sample footage requires an HTTPS source URL")
        if (self.animal_latitude is None) != (self.animal_longitude is None):
            raise ValueError("Provide both animal coordinates or neither")
        if self.captured_at and self.captured_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Capture time is in the future")
        if self.source_kind == "operator_capture" and self.captured_at is None:
            raise ValueError("Operator evidence requires a capture time")
        return self


class MonitoringDecision(Contract):
    revision: int = Field(ge=0)
    confirmed: Literal[True]
    action: Literal["continue", "escalate", "finish"]
    reason: str = Field(min_length=1, max_length=2000)
    next_review_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def schedule(self):
        if self.action == "continue":
            if not self.next_review_at or self.next_review_at <= datetime.now(UTC):
                raise ValueError("Continue monitoring requires a future review time")
        elif self.next_review_at is not None:
            raise ValueError("Only continued monitoring has a next review time")
        return self
