"""Case-scoped stream grants, sampled previews and explicit evidence selection."""

import base64
import hashlib
import io
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select, update

from lifejacket.access.policy import US_STATES
from lifejacket.config import settings
from lifejacket.models.tables import (
    CaseDroneEvidenceRow,
    CaseDroneRequestRow,
    CaseDroneStreamRow,
    IncidentRow,
    NetworkCaseRow,
)
from lifejacket.services import drone_requests as requests

STALE_SECONDS = 6
BUFFER_SECONDS = 12
MAX_FRAMES = 20


def enabled():
    if not (
        settings.network_auth_enabled
        and settings.case_drone_requests_enabled
        and settings.drone_streams_enabled
        and len(settings.drone_stream_receiver_secret) >= 32
    ):
        raise HTTPException(503, "Drone streaming is not configured")


def active(db, row):
    request = db.get(CaseDroneRequestRow, row.request_id)
    scope = db.get(NetworkCaseRow, request.incident_id) if request else None
    incident = db.get(IncidentRow, request.incident_id) if request else None
    return bool(
        request
        and request.status == "in_progress"
        and scope
        and scope.submitted
        and scope.verified_at is not None
        and bool(scope.verified_by and scope.verified_by.strip())
        and scope.state_code in US_STATES
        and incident
        and scope.lead_org_id == row.lead_org_id
        and scope.response_phase != "closed"
        and incident.status not in {"resolved", "cancelled", "duplicate"}
        and not row.ended_at
        and row.expires_at > requests.now()
    )


def get(db, request_id, stream_id):
    row = db.get(CaseDroneStreamRow, stream_id)
    if row is None or row.request_id != request_id:
        raise HTTPException(404, "Stream unavailable")
    return row


def state(db, row, writable=False):
    clock = requests.now()
    frame = row.frames_json[-1] if row.frames_json else None
    age = (
        (clock - datetime.fromisoformat(frame["received_at"].rstrip("Z"))).total_seconds()
        if frame
        else None
    )
    status = (
        "ended"
        if row.ended_at
        else "expired"
        if row.expires_at <= clock
        else "ended"
        if not active(db, row)
        else "waiting"
        if frame is None
        else "interrupted"
        if age > STALE_SECONDS
        else "connected"
    )
    return {
        "stream_id": row.stream_id,
        "request_id": row.request_id,
        "status": status,
        "created_at": row.created_at.isoformat() + "Z",
        "expires_at": row.expires_at.isoformat() + "Z",
        "last_frame_at": frame["received_at"] if frame else None,
        "frame_age_seconds": max(0, age) if age is not None else None,
        "source": row.source_json,
        "can_manage": writable and active(db, row),
        "recording_enabled": settings.drone_recordings_enabled,
        "preview_fps": 2,
        "stale_after_seconds": STALE_SECONDS,
    }


def create(db, actor, case_id, request_id, body):
    _, case = requests.access(db, actor, case_id, write=True)
    request = requests.get(db, case_id, request_id)
    if request.status != "in_progress":
        raise HTTPException(409, "Start evidence collection before opening a stream")
    incident = db.get(IncidentRow, case_id)
    if incident is None or incident.status in {"resolved", "cancelled", "duplicate"}:
        raise HTTPException(409, "This case is no longer collecting observation evidence")
    rows = db.scalars(
        select(CaseDroneStreamRow).where(CaseDroneStreamRow.request_id == request_id)
    ).all()
    if any(active(db, row) for row in rows):
        raise HTTPException(409, "End the existing stream before opening another")
    try:
        base = urlsplit(settings.drone_stream_publish_base)
    except ValueError as exc:
        raise HTTPException(503, "Invalid receiver configuration") from exc
    if (
        base.scheme not in {"rtmp", "rtmps"}
        or not base.hostname
        or base.path != "/live"
        or base.query
        or base.fragment
        or base.username
        or base.password
    ):
        raise HTTPException(503, "Invalid receiver configuration")
    # Plain RTMP is restricted to private-network operation; deployment guidance
    # requires a VPN when DJI Fly cannot negotiate RTMPS.
    if base.scheme == "rtmp":
        import ipaddress

        try:
            address = ipaddress.ip_address(base.hostname)
            private_host = address.is_private and not address.is_unspecified
        except ValueError:
            private_host = base.hostname == "localhost"
        if not private_host:
            raise HTTPException(503, "Use RTMPS or a private receiver address")
    token = secrets.token_urlsafe(32)
    row = CaseDroneStreamRow(
        stream_id=uuid.uuid4().hex,
        request_id=request_id,
        lead_org_id=case.lead_org_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        source_json={
            "source_kind": "sample_footage"
            if request.payload_json["execution_kind"] == "recorded_demo"
            else "operator_capture",
            "source_url": body.source_url,
            "rights_note": body.rights_note,
            "label": body.label,
        },
        frames_json=[],
        created_at=requests.now(),
        expires_at=requests.now() + timedelta(minutes=30),
        ended_at=None,
    )
    if row.source_json["source_kind"] == "sample_footage":
        try:
            source = urlsplit(body.source_url or "")
        except ValueError as exc:
            raise HTTPException(422, "Invalid recording source reference") from exc
        if (
            source.scheme != "https"
            or not source.hostname
            or source.username
            or source.password
        ):
            raise HTTPException(422, "Recorded rehearsal requires an HTTPS source reference")
    requests.compare_swap(db, request, body.revision)
    db.add(row)
    requests.event(
        db,
        request,
        actor,
        "stream_created",
        {"stream_id": row.stream_id, "source_kind": row.source_json["source_kind"]},
    )
    db.commit()
    # Returned once to the managing coordinator; not persisted in cleartext.
    return {
        **state(db, row, True),
        "revision": request.revision,
        "publish_url": settings.drone_stream_publish_base.rstrip("/")
        + "/"
        + row.stream_id
        + "?"
        + urlencode({"user": "publisher", "pass": token}),
    }


def authorize(db, body):
    """MediaMTX HTTP auth. Public viewer access always uses case routes."""
    enabled()
    import ipaddress

    try:
        local = ipaddress.ip_address(body.get("ip", "")).is_loopback
    except ValueError:
        local = False
    receiver = body.get("user") == "receiver" and secrets.compare_digest(
        str(body.get("password", "")), settings.drone_stream_receiver_secret
    )
    if receiver and local and body.get("action") == "api":
        return {}
    path = body.get("path", "")
    parts = path.split("/")
    row = (
        db.get(CaseDroneStreamRow, parts[1])
        if len(parts) == 2 and parts[0] == "live"
        else None
    )
    if row is None or not active(db, row):
        raise HTTPException(401, "Stream unavailable")
    if receiver and local and body.get("action") == "read" and body.get("protocol") == "rtsp":
        return {"expireAt": row.expires_at.isoformat() + "Z"}
    if (
        body.get("action") == "publish"
        and body.get("protocol") == "rtmp"
        and body.get("user") == "publisher"
    ):
        token = str(body.get("password", ""))
        if secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row.token_hash):
            return {"expireAt": row.expires_at.isoformat() + "Z"}
    raise HTTPException(401, "Stream unavailable")


def receive(db, stream_id, data):
    enabled()
    row = db.get(CaseDroneStreamRow, stream_id)
    if row is None or not active(db, row):
        return False
    if not data or len(data) > 256 * 1024:
        raise ValueError("Preview must be at most 256 KiB")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "JPEG" or image.width * image.height > 1_000_000:
            raise ValueError("Invalid bounded JPEG preview")
        image.verify()
    clock = requests.now()
    frame = {
        "frame_id": uuid.uuid4().hex,
        "received_at": clock.isoformat() + "Z",
        "sha256": hashlib.sha256(data).hexdigest(),
        "jpeg_base64": base64.b64encode(data).decode(),
    }
    frames = [
        f
        for f in row.frames_json
        if (clock - datetime.fromisoformat(f["received_at"].rstrip("Z"))).total_seconds()
        <= BUFFER_SECONDS
    ]
    changed = db.execute(
        update(CaseDroneStreamRow)
        .where(
            CaseDroneStreamRow.stream_id == stream_id,
            CaseDroneStreamRow.ended_at.is_(None),
            CaseDroneStreamRow.expires_at > clock,
        )
        .values(frames_json=(frames + [frame])[-MAX_FRAMES:])
    )
    db.commit()
    return changed.rowcount == 1


def preview(db, row, writable=False):
    value = state(db, row, writable)
    if value["status"] != "connected":
        return {**value, "frame": None}
    return {**value, "frame": row.frames_json[-1]}


def capture(db, actor, case_id, request_id, stream_id, body):
    requests.access(db, actor, case_id, write=True)
    request = requests.get(db, case_id, request_id)
    row = get(db, request_id, stream_id)
    if not active(db, row):
        raise HTTPException(409, "Stream is no longer collecting evidence")
    frame = next((f for f in row.frames_json if f["frame_id"] == body.frame_id), None)
    if (
        not frame
        or (
            requests.now() - datetime.fromisoformat(frame["received_at"].rstrip("Z"))
        ).total_seconds()
        > BUFFER_SECONDS
    ):
        raise HTTPException(409, "Selected frame expired; select a fresh frame")
    eid = uuid.uuid4().hex
    path = settings.drone_evidence_dir / "case-requests" / eid
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        **row.source_json,
        "description": body.description,
        "source_session_id": stream_id,
        "source_frame_id": frame["frame_id"],
        "received_at": frame["received_at"],
        "captured_at": None,
        "frame_offset_seconds": None,
        "animal_latitude": None,
        "animal_longitude": None,
        "uploaded_by": actor.user_id,
        "time_note": (
            "Server reception time; camera capture time and source video offset are unknown."
        ),
    }
    data = base64.b64decode(frame["jpeg_base64"])
    try:
        requests.compare_swap(db, request, body.revision)
        path.write_bytes(data)
        db.add(
            CaseDroneEvidenceRow(
                evidence_id=eid,
                request_id=request_id,
                storage_path=str(path),
                content_type="image/jpeg",
                sha256=frame["sha256"],
                metadata_json=meta,
                created_at=requests.now(),
            )
        )
        requests.event(
            db,
            request,
            actor,
            "stream_frame_saved",
            {"stream_id": stream_id, "evidence_id": eid, "frame_id": frame["frame_id"]},
        )
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return {"evidence_id": eid, "revision": request.revision}


def end(db, actor, case_id, request_id, stream_id, body):
    requests.access(db, actor, case_id, write=True)
    request = requests.get(db, case_id, request_id)
    row = get(db, request_id, stream_id)
    if row.ended_at:
        raise HTTPException(409, "Stream already ended")
    requests.compare_swap(db, request, body.revision)
    row.ended_at = requests.now()
    row.frames_json = []
    requests.event(db, request, actor, "stream_ended", {"stream_id": stream_id})
    db.commit()
    return {**state(db, row), "revision": request.revision}
