"""Recorded changes and current carryover, deliberately kept separate."""

from datetime import datetime

from pydantic import BaseModel

from lifejacket.models.coordination import PendingTask


class RecordedEvent(BaseModel):
    event_id: int
    incident_id: str
    recorded_at: datetime
    kind: str
    actor_ref: str | None
    details: dict
    source_ref: str


class CarryoverCase(BaseModel):
    incident_id: str
    headline: str | None
    status: str
    severity_level: str | None
    assigned_responder_id: str | None
    tasks: list[PendingTask]
    source_ref: str


class ShiftHandover(BaseModel):
    start: datetime
    end: datetime
    generated_at: datetime
    scope: str = "installation-wide"
    changes: list[RecordedEvent]
    current_carryover: list[CarryoverCase]
    changes_truncated: bool
    carryover_truncated: bool
    limitations: list[str]
