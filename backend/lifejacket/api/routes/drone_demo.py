"""Opt-in demo queue with no path to real incidents, assignments or center contact."""

import hashlib
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifejacket.config import settings
from lifejacket.drones.grouping import suggest_groups
from lifejacket.models.db import get_session
from lifejacket.models.drone_demo import DemoFrameMetadata, DemoReview
from lifejacket.models.tables import DroneDemoFrameRow
from lifejacket.services.drone_demo import frame_out, review


def enabled():
    if not settings.drone_demo_enabled:
        raise HTTPException(404, "Demo queue is disabled in this environment")


router = APIRouter(
    prefix="/drone-demo", tags=["demo-only evidence"], dependencies=[Depends(enabled)]
)
MAX_BYTES = 2 * 1024 * 1024


def get_frame(session, demo_id):
    row = session.get(DroneDemoFrameRow, demo_id)
    if row is None:
        raise HTTPException(404, "Demo frame not found")
    return row


@router.get("/frames")
def frames(session: Session = Depends(get_session)):
    rows = session.scalars(
        select(DroneDemoFrameRow).order_by(DroneDemoFrameRow.created_at.desc()).limit(100)
    ).all()
    return [frame_out(row) for row in rows]


@router.post("/frames")
async def upload(
    metadata: str = Form(...),
    photo: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    try:
        body = DemoFrameMetadata.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid demo metadata") from exc
    data = await photo.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, "Demo JPEG must contain 1 byte to 2 MiB")
    if hashlib.sha256(data).hexdigest() != body.frame_sha256:
        raise HTTPException(422, "Frame hash does not match the uploaded evidence")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG" or max(image.size) > 1280:
                raise ValueError("Unsupported demo frame")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Use an extracted JPEG with max edge 1280 pixels") from exc
    # One frame/offset per source/kind; repeated imports cannot reset a review.
    key = hashlib.sha256(
        f"{body.evidence_kind}:{body.source_sha256}:{body.offset_seconds}".encode()
    ).hexdigest()
    existing = session.scalar(
        select(DroneDemoFrameRow).where(DroneDemoFrameRow.import_key == key)
    )
    payload = body.model_dump(mode="json")
    if existing:
        if existing.metadata_json != payload:
            raise HTTPException(409, "Existing demo frame has different metadata")
        return frame_out(existing)
    demo_id = "demo_" + uuid.uuid4().hex
    settings.drone_demo_dir.mkdir(parents=True, exist_ok=True)
    path = settings.drone_demo_dir / f"{demo_id}.jpg"
    path.write_bytes(data)
    row = DroneDemoFrameRow(
        demo_id=demo_id,
        import_key=key,
        metadata_json=payload,
        storage_path=str(path),
        status="pending",
        revision=0,
        reviews_json=[],
    )
    try:
        session.add(row)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        path.unlink(missing_ok=True)
        raise HTTPException(409, "Concurrent import; retry the same frame") from exc
    except Exception:
        session.rollback()
        path.unlink(missing_ok=True)
        raise
    return frame_out(row)


@router.get("/frames/{demo_id}/photo")
def photo(demo_id: str, session: Session = Depends(get_session)):
    row = get_frame(session, demo_id)
    path = Path(row.storage_path)
    if not path.is_file():
        raise HTTPException(404, "Demo evidence unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != row.metadata_json["frame_sha256"]:
        raise HTTPException(409, "Demo evidence integrity check failed")
    return FileResponse(
        path, media_type="image/jpeg", headers={"X-Content-Type-Options": "nosniff"}
    )


@router.post("/frames/{demo_id}/review")
def save_review(demo_id: str, body: DemoReview, session: Session = Depends(get_session)):
    row = get_frame(session, demo_id)
    try:
        return review(session, row, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/groups")
def groups(
    source_sha256: str = Query(pattern=r"^[0-9a-f]{64}$"),
    evidence_kind: str = Query(pattern=r"^(toy_demo|synthetic_test)$"),
    session: Session = Depends(get_session),
):
    rows = session.scalars(
        select(DroneDemoFrameRow)
        .where(
            DroneDemoFrameRow.metadata_json["source_sha256"].as_string() == source_sha256,
            DroneDemoFrameRow.metadata_json["evidence_kind"].as_string() == evidence_kind,
        )
        .limit(61)
    ).all()
    if not rows:
        raise HTTPException(404, "Demo source not found")
    try:
        frames = [frame_out(row) for row in rows]
        return {**suggest_groups(frames), "frames": frames}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
