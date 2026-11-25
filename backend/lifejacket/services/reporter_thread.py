"""The thread between a coordinator and the person who filed one report.

Two sides, two kinds of access:

- **Coordinator:** a legacy console route, like the rest of the local console
  (no sign-in; network mode blocks it with every other legacy route).
- **Reporter:** must present the per-report key issued by `/intake/start`.
  Incident IDs are short and read aloud over radios, so knowing one is not
  permission to read what a coordinator wrote to the reporter, or to reply as
  them. Every failure looks the same, so the API does not reveal which
  incidents exist.

The reporter sees text, direction and time only (`ReporterMessage`). Either
side may write first: the reporter app has a Communications tab for exactly
that ("it moved into the water"), and the console's Communications tab lists
every thread with the ones awaiting a reply on top, so a message from a
reporter is not left in an inbox nobody opens.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifejacket.models.coordinator import (
    CoordinatorThread,
    MyReport,
    ReporterMessage,
    ReportRef,
    ThreadMessage,
    ThreadSummary,
)
from lifejacket.models.tables import IncidentMessageRow, IncidentRow, ReporterThreadKeyRow
from lifejacket.services.events import record_event
from lifejacket.services.volunteers import as_utc, utc_now

MAX_BODY_CHARS = 1000
#: A cap on one thread, so neither side can grow a report without bound.
MAX_THREAD_MESSAGES = 200

_DENIED = "Not authorised for this report's messages"


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def issue_key(session: Session, incident_id: str) -> str:
    """Create the report's key. Returned once; only its hash is kept."""
    key = secrets.token_urlsafe(24)
    row = session.get(ReporterThreadKeyRow, incident_id)
    if row is None:
        session.add(
            ReporterThreadKeyRow(
                incident_id=incident_id, key_sha256=_digest(key), created_at=utc_now()
            )
        )
    else:
        row.key_sha256 = _digest(key)
    return key


def reporter_connected(session: Session, incident_id: str) -> bool:
    return session.get(ReporterThreadKeyRow, incident_id) is not None


def check_key(session: Session, incident_id: str, presented: str | None) -> None:
    """Raise 403 unless `presented` is this report's key."""
    row = session.get(ReporterThreadKeyRow, incident_id)
    expected = row.key_sha256 if row is not None else _digest(secrets.token_urlsafe(24))
    # Compare even when there is no row, so timing does not say whether it exists.
    matched = hmac.compare_digest(expected, _digest(presented or ""))
    if row is None or not presented or not matched:
        raise HTTPException(status_code=403, detail=_DENIED)


def _rows(session: Session, incident_id: str) -> list[IncidentMessageRow]:
    return list(
        session.scalars(
            select(IncidentMessageRow)
            .where(IncidentMessageRow.incident_id == incident_id)
            .order_by(IncidentMessageRow.created_at, IncidentMessageRow.id)
        )
    )


def post(
    session: Session, incident_id: str, sender: str, body: str, author_ref: str | None
) -> IncidentMessageRow:
    text = body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="The message is empty")
    if len(text) > MAX_BODY_CHARS:
        raise HTTPException(status_code=422, detail="The message is too long")

    count = session.execute(
        select(func.count()).where(IncidentMessageRow.incident_id == incident_id)
    ).scalar_one()
    if count >= MAX_THREAD_MESSAGES:
        raise HTTPException(status_code=409, detail="This conversation is full")
    if sender == "coordinator" and not reporter_connected(session, incident_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "This report did not come from the reporter app, or was filed before "
                "messaging existed, so there is no way to reach the reporter here."
            ),
        )

    row = IncidentMessageRow(
        incident_id=incident_id,
        sender=sender,
        body=text,
        author_ref=author_ref if sender == "coordinator" else None,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    # The text stays out of the event record, which reaches agent prompts.
    record_event(
        session,
        incident_id,
        "reporter_message_sent" if sender == "coordinator" else "reporter_message_received",
        {"message_id": row.id},
        author_ref if sender == "coordinator" else "reporter",
    )
    return row


def coordinator_view(session: Session, incident_id: str) -> CoordinatorThread:
    return CoordinatorThread(
        incident_id=incident_id,
        reporter_connected=reporter_connected(session, incident_id),
        messages=[
            ThreadMessage(
                message_id=row.id,
                sender=row.sender,
                body=row.body,
                author_ref=row.author_ref,
                created_at=as_utc(row.created_at),
            )
            for row in _rows(session, incident_id)
        ],
    )


def reporter_message(row: IncidentMessageRow) -> ReporterMessage:
    return ReporterMessage(
        message_id=row.id,
        sender="team" if row.sender == "coordinator" else "you",
        body=row.body,
        sent_at=as_utc(row.created_at),
    )


def reporter_view(session: Session, incident_id: str) -> list[ReporterMessage]:
    return [reporter_message(row) for row in _rows(session, incident_id)]


#: Intake has not finished while an incident is in one of these.
_IN_INTAKE = {"intake", "identifying", "assessing"}


def _local(value: datetime) -> datetime:
    """Incident timestamps are naive *local* time (unlike messages, naive UTC)."""
    return value.astimezone(UTC)


def _key_matches(session: Session, incident_id: str, presented: str) -> bool:
    row = session.get(ReporterThreadKeyRow, incident_id)
    expected = row.key_sha256 if row is not None else _digest(secrets.token_urlsafe(24))
    return hmac.compare_digest(expected, _digest(presented)) and row is not None


def my_reports(session: Session, refs: list[ReportRef]) -> list[MyReport]:
    """The reports these keys open, in the order asked; others are left out.

    A key that does not match is skipped rather than failing the batch: a
    phone may hold a report from a database that has since been reset, and
    that should not hide the rest. Skipping looks the same whether the report
    exists or not.
    """
    reports: list[MyReport] = []
    for ref in refs:
        if not _key_matches(session, ref.incident_id, ref.reporter_key):
            continue
        incident = session.get(IncidentRow, ref.incident_id)
        if incident is None:
            continue
        messages = _rows(session, ref.incident_id)
        reports.append(
            MyReport(
                incident_id=incident.incident_id,
                status=incident.status,
                complete=incident.status not in _IN_INTAKE,
                species_common_name=incident.species_common_name,
                severity_level=incident.severity_level,
                place_name=incident.place_name,
                latitude=incident.latitude,
                longitude=incident.longitude,
                created_at=_local(incident.created_at),
                updated_at=_local(incident.updated_at),
                message_count=len(messages),
                team_message_count=sum(1 for m in messages if m.sender == "coordinator"),
                last_message=reporter_message(messages[-1]) if messages else None,
            )
        )
    return reports


def thread_summaries(session: Session, limit: int = 100) -> list[ThreadSummary]:
    """Every report a reporter can be messaged on, replies owed first.

    Only reports with a key: anything else has no one at the other end. Then
    the most recent activity, so a quiet old case sinks.
    """
    incidents = list(
        session.scalars(
            select(IncidentRow)
            .join(
                ReporterThreadKeyRow,
                ReporterThreadKeyRow.incident_id == IncidentRow.incident_id,
            )
            .order_by(IncidentRow.created_at.desc())
            .limit(limit)
        )
    )
    by_incident: dict[str, list[IncidentMessageRow]] = {i.incident_id: [] for i in incidents}
    if incidents:
        for row in session.scalars(
            select(IncidentMessageRow)
            .where(IncidentMessageRow.incident_id.in_(list(by_incident)))
            .order_by(IncidentMessageRow.created_at, IncidentMessageRow.id)
        ):
            by_incident[row.incident_id].append(row)

    summaries: list[ThreadSummary] = []
    for incident in incidents:
        messages = by_incident[incident.incident_id]
        last = messages[-1] if messages else None
        summaries.append(
            ThreadSummary(
                incident_id=incident.incident_id,
                headline=incident.report_headline,
                species_common_name=incident.species_common_name,
                place_name=incident.place_name,
                severity_level=incident.severity_level,
                status=incident.status,
                reporter_phone=incident.reporter_phone,
                message_count=len(messages),
                last_message=(
                    ThreadMessage(
                        message_id=last.id,
                        sender=last.sender,
                        body=last.body,
                        author_ref=last.author_ref,
                        created_at=as_utc(last.created_at),
                    )
                    if last
                    else None
                ),
                awaiting_reply=last is not None and last.sender == "reporter",
                last_activity_at=(
                    as_utc(last.created_at) if last else _local(incident.created_at)
                ),
            )
        )
    summaries.sort(key=lambda t: (not t.awaiting_reply, -t.last_activity_at.timestamp()))
    return summaries
