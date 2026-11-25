"""What the intake pipeline is doing right now, for the reporter's waiting line.

One reporter request can run several model calls in a row -- after the last
assessment answer: assessment, the cross-check, the report and the guardrail,
each a few seconds. A spinner saying "Working..." for twenty seconds reads as
stuck; "Double-checking the facts against your photo" reads as care.

Kept in process memory, keyed by incident. The reporter app polls
`GET /intake/{id}/progress` while its own request is in flight. It is a
display hint and nothing more: never persisted, a missing entry only means a
generic label, and entries expire on their own, so a request that died
mid-step cannot leave a stale step on someone's screen. A deployment with
several worker processes would need a shared store; the local server is one.
"""

from __future__ import annotations

import time

#: Steps, in the order a report usually meets them. The app owns the wording.
STEPS = (
    "context",  # tide, weather, daylight and place name for the location
    "detection",
    "identification",
    "assessment",
    "validation",  # the cross-check of the record against the photo
    "report",
    "guardrail",
    "matching",  # ranking rescue centres
)

#: Longer than any single step takes, even with the client's retries.
STALE_AFTER_SECONDS = 180.0

_steps: dict[str, tuple[str, float]] = {}


def mark(incident_id: str, step: str) -> None:
    """Record that `step` has started for this incident."""
    _steps[incident_id] = (step, time.monotonic())


def clear(incident_id: str) -> None:
    """The request finished: nothing is running for this incident."""
    _steps.pop(incident_id, None)


def current(incident_id: str) -> str | None:
    """The step running now, or None if nothing is (or it went quiet)."""
    entry = _steps.get(incident_id)
    if entry is None:
        return None
    step, started = entry
    if time.monotonic() - started > STALE_AFTER_SECONDS:
        _steps.pop(incident_id, None)
        return None
    return step
