"""Structured results for read-only coordination tools."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HistoryEntry(BaseModel):
    source_ref: str
    incident_id: str
    recorded_at: datetime
    kind: str
    data: dict[str, Any]


class IncidentHistory(BaseModel):
    incident_id: str
    status: str
    assigned_responder_id: str | None
    duplicate_of: str | None
    entries: list[HistoryEntry]
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Status is the current snapshot; only explicit recorded_event "
            "entries establish changes.",
            "Event history starts at feature rollout; older responses are snapshots only.",
            "Legacy snapshot times have no timezone; new recorded events use UTC.",
            "Recorded timestamps are not necessarily animal observation times.",
        ]
    )


class AssignmentRecord(BaseModel):
    assignment_id: int
    incident_id: str
    responder_id: str
    responder_name: str | None
    status: str
    offered_at: datetime
    responded_at: datetime | None
    match_score: float | None
    match_rationale: str | None
    source_ref: str


class PendingTask(BaseModel):
    incident_id: str
    kind: Literal["needs_assignment", "awaiting_response", "human_review"]
    reason: str
    source_refs: list[str]
    derived: bool = True


class AvailableResponder(BaseModel):
    responder_id: str
    name: str
    kind: str
    response_area: str | None
    response_type: str | None
    active_assignment_ids: list[int]
    source_ref: str
    availability_basis: str = "Recorded active and on-duty flags; capacity is not recorded."


class CoordinationAttention(BaseModel):
    task: PendingTask
    proposed_next_step: str


class CoordinationResult(BaseModel):
    incident_id: str
    status: Literal["completed", "held_for_review"]
    attention_items: list[CoordinationAttention] = Field(default_factory=list)
    responders_for_review: list[AvailableResponder] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    human_approval_required: bool = True
