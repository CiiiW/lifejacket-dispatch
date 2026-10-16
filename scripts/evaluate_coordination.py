"""Evaluate five fictional coordination cases without touching application data.

Run with PYTHONPATH=backend. Offline is the default; --live requires ADC and
uses the configured Vertex AI model. Outputs separate scripted checks from
live model results, including latency and model-reported token usage.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from lifejacket.agents.coordination import CoordinationAgent
from lifejacket.config import settings
from lifejacket.llm.client import LLMClient, LLMError
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.models.tables import AssignmentRow, Base, IncidentRow, ResponderRow
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

CASES = {
    "declined_assignment": ("awaiting_dispatch", "declined", False, ["needs_assignment"]),
    "unanswered_offer": ("dispatched", "offered", False, ["awaiting_response"]),
    "accepted_assignment": ("accepted", "accepted", False, []),
    "human_review": ("accepted", "accepted", True, ["human_review"]),
    "closed_case": ("resolved", "completed", False, []),
}


class MeasuredClient:
    """Record usage returned by the existing model client, including failures."""

    def __init__(self, client):
        self.client = client
        self.calls = []

    def generate_json(self, **kwargs):
        started = time.monotonic()
        try:
            response = self.client.generate_json(**kwargs)
        except Exception as exc:
            self.calls.append(
                {
                    "status": "failed",
                    "latency_seconds": time.monotonic() - started,
                    "attempts": exc.attempts if isinstance(exc, LLMError) else None,
                    "prompt_tokens": None,
                    "output_tokens": None,
                }
            )
            raise
        self.calls.append(
            {
                "status": "completed",
                "latency_seconds": response.latency_seconds,
                "attempts": response.attempts,
                "prompt_tokens": response.prompt_tokens,
                "output_tokens": response.output_tokens,
            }
        )
        return response


def _decision(tool="", tasks=(), responders=()):
    return {
        "coordination_action": "tool" if tool else "finish",
        "tool_name": tool,
        "task_kinds": list(tasks),
        "responder_ids": list(responders),
    }


def _offline_client(expected):
    replies = [
        _decision("get_assignments"),
        _decision("get_incident_history"),
        _decision("get_pending_tasks"),
    ]
    responders = []
    if "needs_assignment" in expected:
        replies.append(_decision("get_available_responders"))
        responders = ["demo_ready"]
    replies.append(_decision(tasks=expected, responders=responders))
    return ScriptedLLMClient().queue("coordination", *replies)


def evaluate(live=False):
    results = []
    for name, (status, assignment_status, review, expected) in CASES.items():
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                session.add_all(
                    [
                        IncidentRow(
                            incident_id=name,
                            status=status,
                            assessment_json={"requires_human_review": review},
                            assigned_responder_id=(
                                "demo_ready" if assignment_status == "accepted" else None
                            ),
                        ),
                        ResponderRow(
                            responder_id="demo_ready",
                            name="Fictional Demo Team",
                            kind="volunteer",
                            is_active=True,
                            is_on_duty=True,
                            response_area="Fictional demo area",
                            response_type="Capabilities not validated for this simulation",
                        ),
                    ]
                )
                session.flush()
                session.add(
                    AssignmentRow(
                        incident_id=name,
                        responder_id="demo_ready",
                        status=assignment_status,
                    )
                )
                session.commit()
                measured = MeasuredClient(LLMClient() if live else _offline_client(expected))
                started = time.monotonic()
                output = CoordinationAgent(measured).run(session, name)
                elapsed = time.monotonic() - started
                actual = sorted(item.task.kind for item in output.attention_items)
                session.refresh(session.get(IncidentRow, name))
                unchanged = session.get(IncidentRow, name).status == status
                assignment_unchanged = (
                    session.query(AssignmentRow).one().status == assignment_status
                )
                checks = {
                    "completed": output.status == "completed",
                    "expected_attention_items": actual == sorted(expected),
                    "required_tools_retrieved": {
                        "get_incident_history",
                        "get_assignments",
                        "get_pending_tasks",
                    }.issubset(output.tool_calls),
                    "no_repeated_tools": len(output.tool_calls) == len(set(output.tool_calls)),
                    "within_decision_budget": len(measured.calls)
                    <= settings.coordination_max_rounds,
                    "no_state_changes": unchanged and assignment_unchanged,
                    "human_approval_preserved": output.human_approval_required,
                }
                results.append(
                    {
                        "case": name,
                        "expected_task_kinds": expected,
                        "actual_task_kinds": actual,
                        "checks": checks,
                        "passed": all(checks.values()),
                        "elapsed_seconds": round(elapsed, 4),
                        "model_calls": measured.calls,
                        "result": output.model_dump(mode="json"),
                    }
                )
        finally:
            engine.dispose()
    return {
        "mode": "live" if live else "scripted_offline",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "model": settings.llm_model if live else "scripted-offline",
        "status": "completed",
        "cases_passed": sum(row["passed"] for row in results),
        "total_cases": len(results),
        "cases": results,
        "limitations": [
            "Fictional fixtures test coordination behavior, "
            "not rescue policy or clinical judgment.",
            "Offline results validate execution only; "
            "they do not measure Gemini decision quality.",
            "Token usage is null when not reported, including failed requests; "
            "no billing estimate is inferred.",
            "Elapsed time includes tool execution; model call latency is recorded separately.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Use Vertex AI; makes billable calls."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    blocked = None
    if args.live:
        import google.auth

        try:
            google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        except google.auth.exceptions.DefaultCredentialsError:
            blocked = {
                "mode": "live",
                "status": "blocked",
                "cases": [],
                "reason": (
                    "Application Default Credentials unavailable. "
                    "Authenticate before rerunning."
                ),
            }
    report = blocked or evaluate(live=args.live)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2)
    )
    return 2 if blocked else (0 if report["cases_passed"] == report["total_cases"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
