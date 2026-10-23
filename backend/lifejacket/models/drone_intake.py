"""Drone evidence and manual external-center handoff contracts."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from lifejacket.models.schemas import AnimalGroup


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class ObservationMetadata(Contract):
    source_kind: Literal["real", "simulation"]
    run_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    latitude: float = Field(ge=32, le=42.5)
    longitude: float = Field(ge=-125, le=-114)
    observed_at: AwareDatetime
    operator: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=2000)
    area_terms: list[str] = Field(min_length=1, max_length=12)
    animal_group: AnimalGroup = AnimalGroup.UNKNOWN

    @model_validator(mode="after")
    def meaningful(self):
        if any(not term.strip() or len(term) > 120 for term in self.area_terms):
            raise ValueError(
                "Provide nonblank county/state area terms of at most 120 characters"
            )
        if self.observed_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Observation time is in the future")
        return self


class RevisionRequest(Contract):
    expected_revision: int = Field(ge=0)
    actor: str = Field(min_length=1, max_length=80)


class ReviewObservation(RevisionRequest):
    decision: Literal["verified", "rejected"]
    note: str = Field(min_length=1, max_length=2000)


class LinkCase(RevisionRequest):
    existing_incident_id: str | None = Field(default=None, min_length=1, max_length=32)


class PrepareHandoff(RevisionRequest):
    center_id: str = Field(min_length=1, max_length=64)
    coverage_and_capability_confirmed: Literal[True]
    contact_details_confirmed: Literal[True]
    verification_source: AnyHttpUrl
    verification_note: str = Field(min_length=1, max_length=2000)


class ContactUpdate(RevisionRequest):
    status: Literal[
        "contact_attempted", "acknowledged", "accepted", "declined", "escalated", "completed"
    ]
    channel: Literal["phone", "email", "other"]
    note: str = Field(min_length=1, max_length=2000)
