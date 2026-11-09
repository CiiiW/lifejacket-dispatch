"""Derived in-app reminders with durable, revision-checked acknowledgments."""

import hashlib
import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from lifejacket.access.cases import participating, professional_query
from lifejacket.access.policy import Role
from lifejacket.models.tables import CaseDroneEvidenceRow, CaseDroneRequestRow, IncidentRow
from lifejacket.services import drone_requests as requests
from lifejacket.services.drone_suggestions import confidence_summary


def attention_items(row, clock=None):
    payload = row.payload_json
    candidates = []
    decision = payload.get("monitoring_decision") or {}
    if decision.get("action") == "escalate" or payload.get("outcome") == "escalation_needed":
        candidates.append(
            (
                "escalation",
                decision.get("reason") or payload.get("review_note"),
                decision.get("decided_at")
                or (payload.get("reassessment") or {}).get("reviewed_at"),
            )
        )
    monitoring = requests.monitoring_item(row, clock)
    if monitoring and monitoring["queue_status"] == "overdue":
        candidates.append(
            (
                "overdue",
                "Scheduled observation review is overdue",
                monitoring["next_review_at"],
            )
        )
    result = []
    acknowledged = payload.get("attention_acknowledgments", {})
    for kind, reason, timestamp in candidates:
        key = hashlib.sha256(
            json.dumps(
                [row.request_id, kind, timestamp, reason], separators=(",", ":")
            ).encode()
        ).hexdigest()
        if key not in acknowledged:
            result.append(
                {
                    "case_id": row.incident_id,
                    "request_id": row.request_id,
                    "revision": row.revision,
                    "kind": kind,
                    "attention_key": key,
                    "reason": reason,
                    "since": timestamp,
                    "objective": payload["objective"],
                    "execution_kind": payload["execution_kind"],
                }
            )
    return result


def involved_rows(session, actor):
    if actor.role not in {Role.CENTER_COORDINATOR, Role.RESCUER}:
        raise HTTPException(403, "Professional case participation required")
    for incident, scope in session.execute(
        professional_query(actor).where(participating(actor))
    ):
        if scope.response_phase == "closed" or incident.status in {
            "resolved",
            "cancelled",
            "duplicate",
        }:
            continue
        _, case = requests.access(session, actor, incident.incident_id)
        for row in session.scalars(
            select(CaseDroneRequestRow).where(
                CaseDroneRequestRow.incident_id == incident.incident_id
            )
        ):
            yield row, case


def queue(session, actor, offset=0, limit=50):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid attention page")
    items = []
    clock = datetime.now(UTC)
    for row, case in involved_rows(session, actor):
        for item in attention_items(row, clock):
            items.append({**item, "can_acknowledge": requests.writable(actor, case)})
    items.sort(
        key=lambda x: (
            x["kind"] != "escalation",
            x["since"] or "",
            x["request_id"],
            x["attention_key"],
        )
    )
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "delivery": "in_app",
        "refresh_seconds": 30,
    }


def acknowledge(session, actor, case_id, request_id, body):
    requests.access(session, actor, case_id, write=True)
    row = requests.get(session, case_id, request_id)
    item = next(
        (
            x
            for x in attention_items(row)
            if x["attention_key"] == body.attention_key and x["kind"] == body.kind
        ),
        None,
    )
    if item is None:
        raise HTTPException(409, "Attention item changed or was acknowledged")
    stamp = {
        "attention_kind": body.kind,
        "note": body.note,
        "actor_user_id": actor.user_id,
        "acknowledged_at": requests.now().isoformat() + "Z",
    }
    payload = {
        **row.payload_json,
        "attention_acknowledgments": {
            **row.payload_json.get("attention_acknowledgments", {}),
            body.attention_key: stamp,
        },
    }
    requests.compare_swap(session, row, body.revision, payload_json=payload)
    requests.event(session, row, actor, "attention_acknowledged", stamp)
    session.commit()
    return requests.out(row, True)


def comparison(session, actor, case_id, request_id, previous_id=None):
    requests.access(session, actor, case_id)
    current = requests.get(session, case_id, request_id)
    previous_id = previous_id or current.payload_json.get("previous_request_id")
    previous = requests.get(session, case_id, previous_id) if previous_id else None
    if previous and previous.request_id == current.request_id:
        raise HTTPException(422, "Choose a different observation")
    incident = session.get(IncidentRow, case_id)

    def observation(row):
        if row is None:
            return None
        evidence = session.scalars(
            select(CaseDroneEvidenceRow)
            .where(CaseDroneEvidenceRow.request_id == row.request_id)
            .order_by(CaseDroneEvidenceRow.created_at)
        ).all()
        return {
            **requests.out(row),
            "evidence": [{"evidence_id": e.evidence_id, **e.metadata_json} for e in evidence],
        }

    return {
        "case_id": case_id,
        "intake": {
            "recorded_at": incident.created_at.isoformat(),
            "animal_group": incident.animal_group,
            "species_common_name": incident.species_common_name,
            "severity_level": incident.severity_level,
            "injury_present": incident.injury_present,
            "entanglement_present": incident.entanglement_present,
            "confidence": confidence_summary(incident),
        },
        "current": observation(current),
        "previous": observation(previous),
        "comparison_is_automated": False,
    }
