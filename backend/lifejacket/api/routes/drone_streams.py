"""Authenticated stream controls; the media receiver uses a separate loopback app."""

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifejacket.access.dependencies import AccessSession, current_access_session
from lifejacket.api.routes.network import private
from lifejacket.models.db import get_session
from lifejacket.models.drone_intake import Contract
from lifejacket.models.tables import CaseDroneStreamRow
from lifejacket.services import drone_requests as requests
from lifejacket.services import drone_streams as streams


class OpenStream(Contract):
    revision: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=120)
    rights_note: str = Field(min_length=1, max_length=1000)
    source_url: str | None = Field(default=None, max_length=2000)


class EndStream(Contract):
    revision: int = Field(ge=0)


class CaptureFrame(EndStream):
    frame_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    description: str = Field(min_length=1, max_length=2000)


router = APIRouter(
    prefix="/network/cases/{case_id}/drone-requests/{request_id}/streams",
    tags=["case drone streams"],
    dependencies=[Depends(streams.enabled)],
)


@router.get("")
def listing(
    case_id: str,
    request_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    _, case = requests.access(db, current.access.principal, case_id)
    requests.get(db, case_id, request_id)
    rows = db.scalars(
        select(CaseDroneStreamRow)
        .where(CaseDroneStreamRow.request_id == request_id)
        .order_by(CaseDroneStreamRow.created_at.desc())
        .limit(20)
    ).all()
    return {
        "streams": [
            streams.state(db, row, requests.writable(current.access.principal, case))
            for row in rows
        ]
    }


@router.post("", status_code=201)
def create(
    case_id: str,
    request_id: str,
    body: OpenStream,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    return streams.create(db, current.access.principal, case_id, request_id, body)


@router.get("/{stream_id}/preview")
def preview(
    case_id: str,
    request_id: str,
    stream_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    _, case = requests.access(db, current.access.principal, case_id)
    requests.get(db, case_id, request_id)
    return streams.preview(
        db,
        streams.get(db, request_id, stream_id),
        requests.writable(current.access.principal, case),
    )


@router.post("/{stream_id}/capture", status_code=201)
def capture(
    case_id: str,
    request_id: str,
    stream_id: str,
    body: CaptureFrame,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    return streams.capture(db, current.access.principal, case_id, request_id, stream_id, body)


@router.post("/{stream_id}/end")
def end(
    case_id: str,
    request_id: str,
    stream_id: str,
    body: EndStream,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    private(response)
    return streams.end(db, current.access.principal, case_id, request_id, stream_id, body)


@router.get("/{stream_id}/recordings")
def recordings(
    case_id: str,
    request_id: str,
    stream_id: str,
    response: Response,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    from lifejacket.services import drone_recordings

    private(response)
    requests.access(db, current.access.principal, case_id)
    requests.get(db, case_id, request_id)
    streams.get(db, request_id, stream_id)
    return drone_recordings.listing(db, stream_id)


@router.get("/{stream_id}/recordings/{recording_id}/{segment_id}")
def recording_video(
    case_id: str,
    request_id: str,
    stream_id: str,
    recording_id: str,
    segment_id: str,
    current: AccessSession = Depends(current_access_session),
    db: Session = Depends(get_session),
):
    from fastapi.responses import FileResponse

    from lifejacket.services import drone_recordings

    requests.access(db, current.access.principal, case_id)
    requests.get(db, case_id, request_id)
    streams.get(db, request_id, stream_id)
    path = drone_recordings.segment(db, stream_id, recording_id, segment_id)
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
