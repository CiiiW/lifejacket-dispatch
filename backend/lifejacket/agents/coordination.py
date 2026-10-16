"""A bounded agent that chooses read-only tools for one coordination check.

Model decisions select tools and order recorded pending items. Public findings
and proposed actions are assembled from verified records, not model prose.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from lifejacket.config import settings
from lifejacket.llm.client import LLMClient, LLMError, get_client
from lifejacket.llm.prompts import render_prompt, system_principles
from lifejacket.llm.schema import STRING_LIST, enum_of, object_schema
from lifejacket.models.coordination import (
    CoordinationAttention,
    CoordinationResult,
    PendingTask,
)
from lifejacket.models.tables import IncidentRow
from lifejacket.services import coordination

logger = logging.getLogger(__name__)

TOOLS = {
    "get_incident_history": coordination.get_incident_history,
    "get_assignments": coordination.get_assignments,
    "get_pending_tasks": coordination.get_pending_tasks,
    "get_available_responders": coordination.get_available_responders,
}
REQUIRED_TOOLS = {"get_incident_history", "get_assignments", "get_pending_tasks"}
NEXT_STEPS = {
    "needs_assignment": (
        "Ask the coordinator to review eligible responders and approve an offer."
    ),
    "awaiting_response": "Ask the coordinator to check the outstanding offer's response.",
    "human_review": "Ask the coordinator to review the assessment and guardrail findings.",
}
DECISION_SCHEMA = object_schema(
    {
        "coordination_action": enum_of("tool", "finish"),
        "tool_name": enum_of("", *TOOLS),
        "task_kinds": STRING_LIST,
        "responder_ids": STRING_LIST,
    }
)


class CoordinationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coordination_action: Literal["tool", "finish"]
    tool_name: Literal[
        "",
        "get_incident_history",
        "get_assignments",
        "get_pending_tasks",
        "get_available_responders",
    ]
    task_kinds: list[str]
    responder_ids: list[str]


class CoordinationAgent:
    """Choose tools, observe results, and return evidence-backed attention items."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_client()

    def run(self, session: Session, incident_id: str) -> CoordinationResult:
        # Fail unknown IDs before making a model call; tool arguments are scoped
        # by the application, never supplied by the model.
        if session.get(IncidentRow, incident_id) is None:
            raise LookupError(f"Unknown incident: {incident_id}")
        observations: dict = {}
        calls: list[str] = []
        limitations = [
            "Read-only check: no assignments, notifications, or case changes were made.",
            "On-duty status does not establish incident eligibility or spare capacity.",
            "Pending items are derived checks, not stored tasks or acknowledgments.",
        ]

        def held(reason: str) -> CoordinationResult:
            return CoordinationResult(
                incident_id=incident_id,
                status="held_for_review",
                tool_calls=calls,
                limitations=limitations,
                failure_reason=reason,
            )

        for _ in range(settings.coordination_max_rounds):
            evidence = json.dumps(observations, ensure_ascii=True)
            if len(evidence) > settings.coordination_max_evidence_chars:
                return held(
                    "Evidence exceeded the request limit; coordinator review is required."
                )
            prompt = render_prompt(
                "coordination/check_case.md",
                incident_id=incident_id,
                tool_catalog=json.dumps(
                    {
                        name: function.__doc__
                        for name, function in TOOLS.items()
                        if name not in observations
                    }
                ),
                workflow_state=json.dumps(
                    {
                        "already_retrieved": calls,
                        "required_tools_remaining": sorted(
                            REQUIRED_TOOLS.difference(observations)
                        ),
                        "finish_allowed": REQUIRED_TOOLS.issubset(observations),
                    }
                ),
                observations=evidence,
            )
            try:
                response = self.client.generate_json(
                    prompt=prompt,
                    schema=DECISION_SCHEMA,
                    system_instruction=system_principles(),
                    temperature=0.1,
                )
                decision = CoordinationDecision.model_validate(response.data)
            except LLMError:
                return held("The coordination model could not produce a usable response.")
            except ValidationError:
                return held("The model returned an invalid coordination decision.")
            except Exception:  # noqa: BLE001 - SDK setup can fail before the client's retries
                logger.exception("Coordination model setup or execution failed")
                return held("The coordination model could not be initialized or executed.")

            if decision.coordination_action == "tool":
                name = decision.tool_name
                if not name or decision.task_kinds or decision.responder_ids:
                    return held("A tool request contained invalid selection fields.")
                if name in observations:
                    return held("The model repeated a tool request; execution stopped.")
                tool = TOOLS[name]
                value = (
                    tool(session)
                    if name == "get_available_responders"
                    else tool(session, incident_id)
                )
                observations[name] = (
                    [item.model_dump(mode="json") for item in value]
                    if isinstance(value, list)
                    else value.model_dump(mode="json")
                )
                calls.append(name)
                if name == "get_incident_history":
                    limitations.extend(value.limitations)
                continue

            if decision.tool_name or not REQUIRED_TOOLS.issubset(observations):
                return held(
                    "The model tried to finish before retrieving the required evidence."
                )
            tasks = {
                item["kind"]: PendingTask.model_validate(item)
                for item in observations["get_pending_tasks"]
            }
            if len(set(decision.task_kinds)) != len(decision.task_kinds) or (
                set(decision.task_kinds) != set(tasks)
            ):
                return held("The response omitted, repeated, or invented a pending item.")
            responders = {
                item["responder_id"]: item
                for item in observations.get("get_available_responders", [])
            }
            if len(set(decision.responder_ids)) != len(decision.responder_ids) or (
                not set(decision.responder_ids).issubset(responders)
            ):
                return held(
                    "The response named a responder absent from retrieved availability."
                )
            if decision.responder_ids and "needs_assignment" not in tasks:
                return held("Responder review was proposed without a missing-assignment item.")
            return CoordinationResult(
                incident_id=incident_id,
                status="completed",
                tool_calls=calls,
                attention_items=[
                    CoordinationAttention(
                        task=tasks[kind],
                        proposed_next_step=NEXT_STEPS[kind],
                    )
                    for kind in decision.task_kinds
                ],
                responders_for_review=[responders[key] for key in decision.responder_ids],
                limitations=limitations,
            )
        return held("The coordination decision budget was exhausted.")
