"""API shapes for the local console's coordinator actions.

Four decisions per incident -- ignore, send a team, send volunteers, send a
drone -- plus the coordinator <-> reporter thread. "Send a team" needs no
shape here: it is the existing `POST /responders/assign` offer.

Two projections are deliberately narrow:

- Volunteers never carry a phone number, only its last four digits. The
  console never needs the number to send an alert, and a list of people's
  numbers is exactly what should not leak from a coordinator's screen.
- A reporter's view of the thread is text, direction and time. Never the
  coordinator's identity, internal notes or anyone's contact details.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

VolunteerTask = Literal["observe", "support"]
AlertStatus = Literal["awaiting_reply", "checked_in", "declined", "cancelled"]
IgnoreReason = Literal[
    "false_report", "healthy_animal", "duplicate", "animal_left", "out_of_area", "other"
]


# --- Volunteers -------------------------------------------------------------


class VolunteerAlertBrief(BaseModel):
    """The latest alert this volunteer got for the incident being viewed."""

    alert_id: int
    status: AlertStatus


class NearbyVolunteer(BaseModel):
    volunteer_id: str
    name: str
    #: Street-level base area, not a home address and not a live position.
    address: str
    latitude: float
    longitude: float
    qualification: Literal["observer", "trained_responder"]
    travel_radius_km: float
    skills: list[str]
    available: bool
    phone_last4: str
    distance_km: float
    #: Within the distance this volunteer said they will travel.
    in_range: bool
    #: Can be alerted for this incident's task right now.
    eligible: bool
    ineligible_reason: str | None = None
    alert: VolunteerAlertBrief | None = None
    fictional: bool


class NearbyVolunteers(BaseModel):
    incident_id: str
    #: What a volunteer would be asked to do, from the triage band.
    task: VolunteerTask
    task_description: str
    #: Volunteers further than this are never returned.
    search_radius_km: float
    volunteers: list[NearbyVolunteer]


class AlertRequest(BaseModel):
    volunteer_ids: list[str] = Field(min_length=1, max_length=12)
    message: str = Field(min_length=1, max_length=480)
    sent_by: str = Field(default="coordinator", min_length=1, max_length=128)


class VolunteerAlertOut(BaseModel):
    alert_id: int
    incident_id: str
    volunteer_id: str
    volunteer_name: str
    phone_last4: str
    task: VolunteerTask
    message: str
    status: AlertStatus
    #: "simulated" while no SMS provider is configured: nothing was sent.
    delivery: Literal["simulated"]
    distance_km: float | None
    sent_at: datetime
    responded_at: datetime | None
    response_note: str | None


class AlertReply(BaseModel):
    """A volunteer's answer, recorded by whoever received it."""

    status: Literal["checked_in", "declined"]
    note: str | None = Field(default=None, max_length=300)
    recorded_by: str = Field(default="coordinator", min_length=1, max_length=128)


class VolunteerSummary(BaseModel):
    total: int
    available: int
    fictional: int


# --- Decisions --------------------------------------------------------------


class IgnoreRequest(BaseModel):
    reason: IgnoreReason
    note: str | None = Field(default=None, max_length=300)
    decided_by: str = Field(default="coordinator", min_length=1, max_length=128)


class IgnoreResult(BaseModel):
    incident_id: str
    status: str
    reason: IgnoreReason
    volunteer_alerts_cancelled: int


class DroneSurveyRequest(BaseModel):
    requested_by: str = Field(default="coordinator", min_length=1, max_length=128)


class DroneSurveyOut(BaseModel):
    """A planned survey over the incident. Simulation only: nothing flies."""

    incident_id: str
    plan_id: str
    status: Literal["ready_for_review", "blocked"]
    blocked_reasons: list[str]
    home_latitude: float
    home_longitude: float
    survey_south: float
    survey_north: float
    survey_west: float
    survey_east: float
    altitude_m: float
    distance_m: float | None
    duration_s: float | None
    estimated_battery_remaining_percent: float | None
    waypoint_count: int
    launch_note: str
    synthetic: Literal[True] = True


class DecisionEntry(BaseModel):
    """One coordinator decision or reply, from the incident's event record."""

    event_id: int
    kind: str
    summary: str
    actor: str | None
    recorded_at: datetime


# --- Coordinator <-> reporter thread ----------------------------------------


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)
    author_ref: str = Field(default="coordinator", min_length=1, max_length=128)


class ThreadMessage(BaseModel):
    """Coordinator view of one message."""

    message_id: int
    sender: Literal["coordinator", "reporter"]
    body: str
    author_ref: str | None
    created_at: datetime


class CoordinatorThread(BaseModel):
    incident_id: str
    #: False when the report did not come from the reporter app (or predates
    #: messaging): nobody holds a key, so nothing written here could be read.
    reporter_connected: bool
    messages: list[ThreadMessage]


class ReporterMessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


class ReporterMessage(BaseModel):
    """Reporter view of one message: text, direction, time. Nothing else."""

    message_id: int
    sender: Literal["team", "you"]
    body: str
    sent_at: datetime


# --- The reporter's own reports, and the console's inbox ---------------------


class ReportRef(BaseModel):
    """A report this device filed, with the key `/intake/start` gave it."""

    incident_id: str = Field(min_length=1, max_length=64)
    reporter_key: str = Field(min_length=1, max_length=128)


class MyReportsRequest(BaseModel):
    """Keys travel in the body, never the URL, so they stay out of access logs."""

    reports: list[ReportRef] = Field(max_length=50)


class MyReport(BaseModel):
    """One of the reporter's own reports, as they may see it.

    Status, animal, place and the thread's shape. Never who handles the case,
    their notes, or anyone's contact details.
    """

    incident_id: str
    status: str
    #: Intake finished: the report reached the rescue network.
    complete: bool
    species_common_name: str | None
    severity_level: str | None
    place_name: str | None
    latitude: float | None
    longitude: float | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    team_message_count: int
    last_message: ReporterMessage | None


class ProgressOut(BaseModel):
    """The intake step running for a report now, or null when idle."""

    step: str | None


class ThreadSummary(BaseModel):
    """One reporter conversation, for the console's Communications tab."""

    incident_id: str
    headline: str | None
    species_common_name: str | None
    place_name: str | None
    severity_level: str | None
    status: str
    #: Shared by the reporter as a condition of using the app.
    reporter_phone: str | None
    message_count: int
    last_message: ThreadMessage | None
    #: The reporter wrote last, so the team owes them an answer.
    awaiting_reply: bool
    last_activity_at: datetime
