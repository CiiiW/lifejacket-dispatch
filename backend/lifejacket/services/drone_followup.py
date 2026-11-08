"""Shared eligibility and durable worker leases for case follow-up."""

import uuid
from datetime import timedelta

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError

from lifejacket.access.policy import US_STATES
from lifejacket.models.tables import DroneWorkerHeartbeatRow, IncidentRow, NetworkCaseRow
from lifejacket.services import drone_requests as requests


def eligible(db, request, org):
    scope = db.get(NetworkCaseRow, request.incident_id) if request else None
    incident = db.get(IncidentRow, request.incident_id) if request else None
    return bool(
        scope
        and incident
        and scope.submitted
        and scope.verified_at
        and scope.verified_by
        and scope.verified_by.strip()
        and scope.state_code in US_STATES
        and scope.lead_org_id == org
        and scope.response_phase != "closed"
        and incident.status not in {"resolved", "cancelled", "duplicate"}
    )


def claimable(table, clock):
    return and_(
        table.next_attempt_at <= clock,
        or_(table.status == "queued", table.status == "running"),
    )


def claim(db, table, row, minutes=5):
    clock = requests.now()
    token = uuid.uuid4().hex
    changed = db.execute(
        update(table)
        .where(
            table.__table__.primary_key.columns.values()[0]
            == getattr(row, table.__table__.primary_key.columns.values()[0].name),
            claimable(table, clock),
        )
        .values(
            status="running",
            lease_token=token,
            attempts=table.attempts + 1,
            next_attempt_at=clock + timedelta(minutes=minutes),
            updated_at=clock,
        ),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    if changed.rowcount != 1:
        return None
    db.refresh(row)
    return token


def finish(db, table, row, token, status, **values):
    key = table.__table__.primary_key.columns.values()[0]
    db.execute(
        update(table)
        .where(
            key == getattr(row, key.name),
            table.status == "running",
            table.lease_token == token,
        )
        .values(status=status, lease_token=None, updated_at=requests.now(), **values),
        execution_options={"synchronize_session": False},
    )
    db.commit()


def heartbeat(db, kind):
    clock = requests.now()
    changed = db.execute(
        update(DroneWorkerHeartbeatRow)
        .where(DroneWorkerHeartbeatRow.worker_kind == kind)
        .values(touched_at=clock)
    )
    if changed.rowcount == 0:
        db.add(DroneWorkerHeartbeatRow(worker_kind=kind, touched_at=clock))
    try:
        db.commit()
    except IntegrityError:
        # Another worker can create the first heartbeat concurrently.
        db.rollback()
        db.execute(
            update(DroneWorkerHeartbeatRow)
            .where(DroneWorkerHeartbeatRow.worker_kind == kind)
            .values(touched_at=clock)
        )
        db.commit()


def worker_status(db, kind):
    row = db.get(DroneWorkerHeartbeatRow, kind)
    return {
        "last_seen_at": row.touched_at.isoformat() + "Z" if row else None,
        "running": bool(row and (requests.now() - row.touched_at).total_seconds() < 90),
    }
