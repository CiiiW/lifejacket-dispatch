"""Durable lead-organization reminders with deduplication and bounded retries."""

import hashlib
import hmac
import json
from datetime import timedelta
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lifejacket.config import settings
from lifejacket.models.tables import (
    AccessOrganizationRow,
    CaseDroneReminderRow,
    CaseDroneRequestRow,
    NetworkCaseRow,
)
from lifejacket.services import (
    drone_attention,
)
from lifejacket.services import (
    drone_followup as common,
)
from lifejacket.services import (
    drone_requests as requests,
)


def enabled():
    if not (
        settings.network_auth_enabled
        and settings.case_drone_requests_enabled
        and settings.drone_reminders_enabled
    ):
        raise HTTPException(503, "Background reminders are not configured")


def configured(org):
    url = settings.drone_reminder_webhooks.get(org, "")
    key = settings.drone_reminder_signing_keys.get(org, "")
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and len(key) >= 32
        )
    except ValueError:
        return False


def target_allowed(db, request, org):
    center = db.get(AccessOrganizationRow, org)
    scope = db.get(NetworkCaseRow, request.incident_id) if request else None
    return bool(
        common.eligible(db, request, org)
        and center
        and center.enabled
        and center.verified_at
        and center.verified_by
        and center.verified_by.strip()
        and scope.state_code in center.approved_states
    )


def current_item(db, row):
    request = db.get(CaseDroneRequestRow, row.request_id)
    if not target_allowed(db, request, row.organization_id):
        return None
    return next(
        (
            x
            for x in drone_attention.attention_items(request)
            if x["attention_key"] == row.attention_key and x["kind"] == row.kind
        ),
        None,
    )


def scan(db):
    enabled()
    clock = requests.now()
    for request in db.scalars(select(CaseDroneRequestRow)):
        scope = db.get(NetworkCaseRow, request.incident_id)
        org = scope.lead_org_id if scope else None
        if not org or not target_allowed(db, request, org):
            continue
        for item in drone_attention.attention_items(request):
            nid = hashlib.sha256(
                (request.request_id + ":" + org + ":" + item["attention_key"]).encode()
            ).hexdigest()
            row = db.get(CaseDroneReminderRow, nid)
            ready = configured(org)
            if row is None:
                db.add(
                    CaseDroneReminderRow(
                        notification_id=nid,
                        request_id=request.request_id,
                        organization_id=org,
                        attention_key=item["attention_key"],
                        kind=item["kind"],
                        status="queued" if ready else "blocked",
                        attempts=0,
                        next_attempt_at=clock,
                        created_at=clock,
                        updated_at=clock,
                        error_code=None if ready else "destination_not_configured",
                    )
                )
            elif row.status == "blocked" and ready:
                row.status = "queued"
                row.error_code = None
                row.next_attempt_at = clock
                row.updated_at = clock
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # another scanner inserted the same durable key
    for row in db.scalars(
        select(CaseDroneReminderRow).where(
            CaseDroneReminderRow.status.in_(["queued", "running", "blocked"])
        )
    ):
        if current_item(db, row) is None:
            row.status = "cancelled"
            row.lease_token = None
            row.updated_at = clock
            row.error_code = "attention_changed"
    db.commit()
    common.heartbeat(db, "reminders")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(url, body, headers):
    # The URL is operator configuration, never a client-provided destination.
    # Provider diagnostics and secret URLs are deliberately not logged/stored.
    with build_opener(NoRedirect()).open(
        Request(url, data=body, headers=headers, method="POST"), timeout=15
    ) as response:
        if not 200 <= response.status < 300:
            raise OSError("delivery_rejected")


def deliver_one(factory, sender=send):
    enabled()
    with factory() as db:
        scan(db)
        row = db.scalar(
            select(CaseDroneReminderRow)
            .where(common.claimable(CaseDroneReminderRow, requests.now()))
            .order_by(CaseDroneReminderRow.created_at)
            .limit(1)
        )
        if row is None:
            return False
        token = common.claim(db, CaseDroneReminderRow, row, minutes=2)
        if not token:
            return False
        if current_item(db, row) is None:
            common.finish(
                db,
                CaseDroneReminderRow,
                row,
                token,
                "cancelled",
                error_code="attention_changed",
            )
            return True
        if not configured(row.organization_id):
            common.finish(
                db,
                CaseDroneReminderRow,
                row,
                token,
                "blocked",
                error_code="destination_not_configured",
            )
            return True
        if row.attempts > 5:
            common.finish(
                db, CaseDroneReminderRow, row, token, "failed", error_code="retry_limit"
            )
            return True
        payload = {
            "schema_version": 1,
            "event": "drone_observation_attention",
            "notification_id": row.notification_id,
            "organization_id": row.organization_id,
            "case_id": db.get(CaseDroneRequestRow, row.request_id).incident_id,
            "request_id": row.request_id,
            "kind": row.kind,
            "attention_key": row.attention_key,
            "created_at": row.created_at.isoformat() + "Z",
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        key = settings.drone_reminder_signing_keys[row.organization_id]
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": row.notification_id,
            "X-LifeJacket-Signature": "sha256="
            + hmac.new(key.encode(), body, hashlib.sha256).hexdigest(),
        }
        destination = settings.drone_reminder_webhooks[row.organization_id]
        db.commit()
        try:
            sender(destination, body, headers)
            common.finish(db, CaseDroneReminderRow, row, token, "delivered", error_code=None)
        except Exception:
            db.rollback()
            status = "failed" if row.attempts >= 5 else "queued"
            common.finish(
                db,
                CaseDroneReminderRow,
                row,
                token,
                status,
                error_code="delivery_failed",
                next_attempt_at=requests.now()
                + timedelta(seconds=min(3600, 30 * 2**row.attempts)),
            )
        return True


def out(row):
    return {
        "notification_id": row.notification_id,
        "kind": row.kind,
        "status": row.status,
        "attempts": row.attempts,
        "error_code": row.error_code,
        "next_attempt_at": row.next_attempt_at.isoformat() + "Z",
        "updated_at": row.updated_at.isoformat() + "Z",
    }


def retry(db, actor, case_id, request_id, body):
    requests.access(db, actor, case_id, write=True)
    request = requests.get(db, case_id, request_id)
    row = db.get(CaseDroneReminderRow, body.notification_id)
    if not (
        row and row.request_id == request_id and row.organization_id == actor.organization_id
    ):
        raise HTTPException(404, "Reminder unavailable")
    if row.status != "failed" or current_item(db, row) is None:
        raise HTTPException(409, "Reminder is no longer eligible for retry")
    if not configured(row.organization_id):
        raise HTTPException(503, "Destination is not configured")
    requests.compare_swap(db, request, body.revision)
    row.status = "queued"
    row.attempts = 0
    row.next_attempt_at = requests.now()
    row.error_code = None
    requests.event(
        db, request, actor, "reminder_retry_queued", {"notification_id": row.notification_id}
    )
    db.commit()
    return {"revision": request.revision, **out(row)}
