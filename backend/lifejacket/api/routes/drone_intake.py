"""Dedicated drone evidence intake; external contact is recorded, never sent."""

import hashlib
import io
import uuid
from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifejacket.agents.base import AgentError
from lifejacket.config import settings
from lifejacket.drones.runs import load_run
from lifejacket.llm.client import LLMClient, get_client
from lifejacket.models.db import get_session
from lifejacket.models.drone_intake import (
    AnalyzeAnimal,
    ContactUpdate,
    LinkCase,
    ObservationMetadata,
    PrepareHandoff,
    ReviewObservation,
    RevisionRequest,
)
from lifejacket.models.schemas import AnimalGroup
from lifejacket.models.tables import DroneObservationRow, ExternalHandoffRow
from lifejacket.services import drone_intake as service
from lifejacket.taxonomy import GROUP_LABELS

router = APIRouter(prefix="/drone-intake", tags=["drone evidence and external handoff"])
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _call(session, function, *args):
    try:
        return function(session, *args)
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.Conflict as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Photo analysis unavailable; evidence is saved. Retry or review manually.",
        ) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _observation(session, observation_id):
    return _call(session, service.observation, observation_id)


@router.get("/animal-groups")
def animal_groups() -> list[dict]:
    return [
        {"value": group.value, "label": GROUP_LABELS.get(group, "Unknown / unsure")}
        for group in AnimalGroup
    ]


@router.get("/observations")
def observations(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(
        select(DroneObservationRow).order_by(DroneObservationRow.created_at.desc()).limit(50)
    ).all()
    return [service.observation_out(row) for row in rows]


@router.post("/observations", status_code=201)
async def upload_observation(
    metadata: str = Form(...),
    photo: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    try:
        body = ObservationMetadata.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.run_id:
        try:
            run = load_run(settings.drone_runs_dir, body.run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Flight run not found") from exc
        if run.get("synthetic") is True and body.source_kind == "real":
            raise HTTPException(
                status_code=409,
                detail="SITL flights cannot establish real evidence provenance",
            )
    data = await photo.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Photo must contain 1 byte to 8 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("Image exceeds 20 megapixels")
            content_type = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
            }.get(image.format)
            if content_type is None:
                raise ValueError("Only JPEG, PNG and WebP photos are supported")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(
            status_code=422, detail="Upload a valid JPEG, PNG or WebP photo under 20 MP"
        ) from exc
    observation_id = uuid.uuid4().hex
    settings.drone_evidence_dir.mkdir(parents=True, exist_ok=True)
    path = settings.drone_evidence_dir / observation_id
    path.write_bytes(data)
    row = DroneObservationRow(
        observation_id=observation_id,
        source_kind=body.source_kind,
        run_id=body.run_id,
        latitude=body.latitude,
        longitude=body.longitude,
        observed_at=body.observed_at.astimezone(UTC).replace(tzinfo=None),
        metadata_json=body.model_dump(mode="json"),
        storage_path=str(path),
        content_type=content_type,
        sha256=hashlib.sha256(data).hexdigest(),
        status="pending",
        revision=0,
    )
    try:
        session.add(row)
        session.commit()
    except Exception:
        session.rollback()
        path.unlink(missing_ok=True)
        raise
    return service.observation_out(row)


@router.get("/observations/{observation_id}/photo")
def evidence_photo(
    observation_id: str, download: bool = False, session: Session = Depends(get_session)
):
    row = _observation(session, observation_id)
    if not Path(row.storage_path).is_file():
        raise HTTPException(status_code=404, detail="Evidence file unavailable")
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[
        row.content_type
    ]
    return FileResponse(
        row.storage_path,
        filename=f"drone-observation-{row.observation_id}.{extension}" if download else None,
        media_type=row.content_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/observations/{observation_id}/centers")
def centers(observation_id: str, session: Session = Depends(get_session)) -> list[dict]:
    return service.directory_candidates(_observation(session, observation_id))


@router.post("/observations/{observation_id}/review")
def review(
    observation_id: str, body: ReviewObservation, session: Session = Depends(get_session)
):
    return _call(session, service.review, _observation(session, observation_id), body)


@router.post("/observations/{observation_id}/detect")
def detect(
    observation_id: str,
    body: RevisionRequest,
    session: Session = Depends(get_session),
    client: LLMClient = Depends(get_client),
):
    return _call(
        session,
        lambda s, row: service.screen_photo(s, row, body, client=client),
        _observation(session, observation_id),
    )


@router.post("/observations/{observation_id}/analyze")
def analyze(
    observation_id: str,
    body: AnalyzeAnimal,
    session: Session = Depends(get_session),
    client: LLMClient = Depends(get_client),
):
    return _call(
        session,
        lambda s, row: service.screen_photo(s, row, body, identify=True, client=client),
        _observation(session, observation_id),
    )


@router.post("/observations/{observation_id}/case")
def case(observation_id: str, body: LinkCase, session: Session = Depends(get_session)):
    return _call(session, service.link_case, _observation(session, observation_id), body)


@router.post("/observations/{observation_id}/handoffs")
def prepare(
    observation_id: str, body: PrepareHandoff, session: Session = Depends(get_session)
):
    return _call(session, service.prepare, _observation(session, observation_id), body)


@router.get("/observations/{observation_id}/handoffs")
def handoffs(observation_id: str, session: Session = Depends(get_session)):
    _observation(session, observation_id)
    rows = session.scalars(
        select(ExternalHandoffRow)
        .where(ExternalHandoffRow.observation_id == observation_id)
        .order_by(ExternalHandoffRow.created_at)
    ).all()
    return [service.handoff_out(row) for row in rows]


@router.post("/handoffs/{handoff_id}/status")
def contact_status(
    handoff_id: str, body: ContactUpdate, session: Session = Depends(get_session)
):
    row = session.get(ExternalHandoffRow, handoff_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return _call(session, service.contact_update, row, body)
