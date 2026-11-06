"""Authenticated, case-scoped drone requests and immutable still-image evidence."""

import hashlib
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifejacket.access.dependencies import AccessSession, current_access_session
from lifejacket.api.routes.network import private
from lifejacket.config import settings
from lifejacket.models.db import get_session
from lifejacket.models.drone_requests import ChangeRequest, CreateRequest, EvidenceMetadata
from lifejacket.models.tables import (
    CaseDroneEventRow,
    CaseDroneEvidenceRow,
    CaseDroneRequestRow,
    IncidentRow,
)
from lifejacket.services import drone_requests as service
from lifejacket.services.drone_suggestions import confidence_summary


def enabled():
    if not settings.network_auth_enabled or not settings.case_drone_requests_enabled:
        raise HTTPException(503, "Case drone requests are not configured")


router = APIRouter(
    prefix="/network/cases/{case_id}/drone-requests",
    tags=["case drone requests"],
    dependencies=[Depends(enabled)],
)


@router.get("")
def listing(
    case_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    _, case = service.access(session, current.access.principal, case_id)
    writable = service.writable(current.access.principal, case)
    rows = session.scalars(
        select(CaseDroneRequestRow)
        .where(
            CaseDroneRequestRow.incident_id == case_id,
        )
        .order_by(CaseDroneRequestRow.created_at.desc())
        .limit(100)
    ).all()
    return {
        "can_create": writable,
        "requests": [service.out(r, writable) for r in rows],
        "suggestions": service.suggestions(session, case_id, case),
        "confidence_summary": confidence_summary(session.get(IncidentRow, case_id)),
    }


@router.post("", status_code=201)
def create(
    case_id: str,
    body: CreateRequest,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    try:
        return service.create(session, current.access.principal, case_id, body)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Request changed; refresh before retrying") from exc


@router.get("/{request_id}")
def detail(
    case_id: str,
    request_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    _, case = service.access(session, current.access.principal, case_id)
    row = service.get(session, case_id, request_id)
    evidence = session.scalars(
        select(CaseDroneEvidenceRow)
        .where(
            CaseDroneEvidenceRow.request_id == request_id,
        )
        .order_by(CaseDroneEvidenceRow.created_at)
    ).all()
    events = session.scalars(
        select(CaseDroneEventRow)
        .where(
            CaseDroneEventRow.request_id == request_id,
        )
        .order_by(CaseDroneEventRow.revision)
    ).all()
    return {
        **service.out(row, service.writable(current.access.principal, case)),
        "evidence": [
            {"evidence_id": e.evidence_id, "sha256": e.sha256, **e.metadata_json}
            for e in evidence
        ],
        "events": [
            {
                "revision": e.revision,
                "kind": e.kind,
                "actor_user_id": e.actor_user_id,
                "recorded_at": e.recorded_at.isoformat() + "Z",
                **e.details_json,
            }
            for e in events
        ],
    }


@router.patch("/{request_id}")
def change(
    case_id: str,
    request_id: str,
    body: ChangeRequest,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    return service.change(session, current.access.principal, case_id, request_id, body)


@router.post("/{request_id}/evidence", status_code=201)
async def upload(
    case_id: str,
    request_id: str,
    response: Response,
    metadata: str = Form(...),
    photo: UploadFile = File(...),
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    private(response)
    actor = current.access.principal
    service.access(session, actor, case_id, write=True)
    row = service.get(session, case_id, request_id)
    if row.status != "in_progress":
        raise HTTPException(409, "Evidence collection is not in progress")
    try:
        body = EvidenceMetadata.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid evidence metadata") from exc
    expected = (
        "sample_footage"
        if row.payload_json["execution_kind"] == "recorded_demo"
        else "operator_capture"
    )
    if body.source_kind != expected:
        raise HTTPException(422, "Evidence source must match the request execution kind")
    data = await photo.read(8 * 1024 * 1024 + 1)
    if not data or len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Upload a still image of at most 8 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("Image too large")
            content_type = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
            }.get(image.format)
            if not content_type:
                raise ValueError("Unsupported image format")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Upload a valid JPEG, PNG or WebP under 20 MP") from exc
    evidence_id = uuid.uuid4().hex
    directory = settings.drone_evidence_dir / "case-requests"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / evidence_id
    meta = body.model_dump(mode="json", exclude={"revision"})
    meta["uploaded_by"] = actor.user_id
    try:
        service.compare_swap(session, row, body.revision)
        path.write_bytes(data)
        session.add(
            CaseDroneEvidenceRow(
                evidence_id=evidence_id,
                request_id=request_id,
                storage_path=str(path),
                content_type=content_type,
                sha256=hashlib.sha256(data).hexdigest(),
                metadata_json=meta,
                created_at=service.now(),
            )
        )
        service.event(
            session,
            row,
            actor,
            "evidence_attached",
            {
                "evidence_id": evidence_id,
                "source_kind": body.source_kind,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        path.unlink(missing_ok=True)
        raise
    return {"evidence_id": evidence_id, "revision": row.revision}


@router.get("/{request_id}/evidence/{evidence_id}/photo")
def photo(
    case_id: str,
    request_id: str,
    evidence_id: str,
    current: AccessSession = Depends(current_access_session),
    session: Session = Depends(get_session),
):
    service.access(session, current.access.principal, case_id)
    service.get(session, case_id, request_id)
    row = session.get(CaseDroneEvidenceRow, evidence_id)
    if row is None or row.request_id != request_id or not Path(row.storage_path).is_file():
        raise HTTPException(404, "Evidence unavailable")
    return FileResponse(
        row.storage_path,
        media_type=row.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Vary": "Authorization, X-LifeJacket-Organization",
        },
    )
