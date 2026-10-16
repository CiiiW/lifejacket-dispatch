"""Per-incident pipeline health: what went wrong on the way to this report.

Retries and fail-safes keep an incident moving when a model call misbehaves,
which is the point -- but it also means a report can reach a coordinator
looking normal after three retries, a failed guardrail check, or no written
report at all. This module keeps the record of that, so "it worked" and "it
worked, but only just" can be told apart.

The record lives in `incident.metrics["health"]`, next to the latencies and
token counts, so it is saved with the incident and travels with it to the
responder console (`GET /incidents/{id}` returns it as `health`):

    {
      "llm_calls": 6,            # model calls attempted for this incident
      "llm_retries": 2,          # extra attempts beyond the first
      "failed_calls": 1,         # calls that failed even after retries
      "failures": [              # one entry per failed call, newest last
        {"agent": "identification", "kind": "call_failed",
         "attempts": 3, "detail": "...", "at": "2026-10-05T14:02:11"}
      ],
      "fallbacks": ["guardrail_check_failed"],   # fail-safes that were used
      "awaiting_retry": false    # reporter was asked to try again, has not yet
    }

`IntakePipeline` is the only writer. Everything here is plain data in, plain
data out, so it is easy to test and safe to import from anywhere.

Not here yet (planned follow-up): trends across incidents -- failure rates per
agent, alerting when they climb, and a second-model diagnosis of bad replies.
This module records the per-incident facts those would be built on.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

HEALTH_KEY = "health"

#: Fail-safe names written to `fallbacks`. Kept as constants so the pipeline,
#: the tests, and the console all spell them the same way.
FALLBACK_GUARDRAIL_CHECK_FAILED = "guardrail_check_failed"
FALLBACK_REPORT_UNAVAILABLE = "report_unavailable"

#: Error text is truncated: it is for a human scanning the console, and the
#: full exception is already in the server log.
_MAX_DETAIL_CHARS = 300
#: Cap on stored failure entries, so a reporter retrying against a long outage
#: cannot grow the incident row without bound. The counters keep counting.
_MAX_FAILURE_ENTRIES = 20


def _empty() -> dict[str, Any]:
    return {
        "llm_calls": 0,
        "llm_retries": 0,
        "failed_calls": 0,
        "failures": [],
        "fallbacks": [],
        "awaiting_retry": False,
    }


def get(metrics: dict[str, Any]) -> dict[str, Any]:
    """The incident's health record, or an all-clear one if nothing is recorded."""
    return {**_empty(), **(metrics.get(HEALTH_KEY) or {})}


def _updated(metrics: dict[str, Any]) -> dict[str, Any]:
    """A fresh copy of the health record to modify and store back.

    A copy, never an in-place edit. `metrics` is saved to a JSON column, and
    SQLAlchemy does not notice edits made inside a JSON value: it only writes
    the column when handed a value that differs from the one it loaded. If the
    nested record were ever shared with the loaded row, an in-place edit would
    change both sides and the update would be skipped without an error.
    Replacing the record means health never depends on that.
    """
    return copy.deepcopy(get(metrics))


def record_success(metrics: dict[str, Any], attempts: int = 1) -> None:
    """Note a model call that produced a usable result, and what it cost in retries."""
    health = _updated(metrics)
    health["llm_calls"] += 1
    health["llm_retries"] += max(attempts - 1, 0)
    # A successful call means the reporter is no longer stuck waiting to retry.
    health["awaiting_retry"] = False
    metrics[HEALTH_KEY] = health


def record_failure(
    metrics: dict[str, Any], agent: str, kind: str, attempts: int, detail: str
) -> None:
    """Note a model call that failed even after its retries."""
    health = _updated(metrics)
    health["llm_calls"] += 1
    health["llm_retries"] += max(attempts - 1, 0)
    health["failed_calls"] += 1
    health["failures"].append(
        {
            "agent": agent,
            "kind": kind,
            "attempts": attempts,
            "detail": detail[:_MAX_DETAIL_CHARS],
            "at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    health["failures"] = health["failures"][-_MAX_FAILURE_ENTRIES:]
    metrics[HEALTH_KEY] = health


def record_fallback(metrics: dict[str, Any], name: str) -> None:
    """Note that a fail-safe was used in place of a model result."""
    health = _updated(metrics)
    if name not in health["fallbacks"]:
        health["fallbacks"].append(name)
    metrics[HEALTH_KEY] = health


def set_awaiting_retry(metrics: dict[str, Any], waiting: bool) -> None:
    """Mark whether the reporter has been asked to try again and has not yet."""
    health = _updated(metrics)
    health["awaiting_retry"] = waiting
    metrics[HEALTH_KEY] = health


def is_awaiting_retry(metrics: dict[str, Any]) -> bool:
    return bool(get(metrics)["awaiting_retry"])


def had_problems(metrics: dict[str, Any]) -> bool:
    """True if anything at all went wrong, including retries that then succeeded.

    Used for the informational note on the console and the log level of the
    summary line.
    """
    health = get(metrics)
    return bool(health["llm_retries"] or health["failed_calls"] or health["fallbacks"])


def needs_review(metrics: dict[str, Any]) -> bool:
    """True if a failure was NOT recovered from, so a human should look.

    A retry that succeeded does not count: the result is as good as any other.
    A fail-safe result, or an intake stalled waiting for the reporter to try
    again, does.
    """
    health = get(metrics)
    return bool(health["fallbacks"] or health["awaiting_retry"])


def summary(metrics: dict[str, Any]) -> str:
    """One line for the log, e.g. 'llm_calls=6 retries=2 failed=1 fallbacks=[...]'."""
    health = get(metrics)
    return (
        f"llm_calls={health['llm_calls']} retries={health['llm_retries']} "
        f"failed={health['failed_calls']} fallbacks={health['fallbacks']}"
    )


def log_summary(incident_id: str, metrics: dict[str, Any]) -> None:
    """Log the incident's health once intake finishes.

    WARNING when anything went wrong, so it stands out in the server log;
    INFO otherwise, so a clean run still leaves a trace.
    """
    level = logging.WARNING if had_problems(metrics) else logging.INFO
    logger.log(level, "Incident %s health: %s", incident_id, summary(metrics))
