"""Private draft -> managed phone identity -> own minimal response status.

Credentials travel in POST bodies, never URLs. This is a dedicated transport
for reporters; professional endpoints continue requiring standard bearer auth.
"""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from lifejacket.access.identity import (
    IdentityUnavailable,
    InvalidIdentity,
    verify_provider_token,
)
from lifejacket.access.memberships import AccessDenied, audit, ensure_account
from lifejacket.access.policy import CaseAccess, Principal, Role
from lifejacket.access.reporter_view import ResponsePhase, reporter_update
from lifejacket.api.routes import intake
from lifejacket.config import settings
from lifejacket.models import repository
from lifejacket.models.db import get_session
from lifejacket.models.schemas import ConversationStage
from lifejacket.models.tables import NetworkCaseRow, ReporterDraftRow


def available(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    if not settings.network_auth_enabled or not settings.reporter_phone_enabled:
        raise HTTPException(503, "Phone-verified reporting is not configured")


router = APIRouter(
    prefix="/reporter", tags=["phone-verified reporter"], dependencies=[Depends(available)]
)


class PrivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class DraftKey(PrivateBody):
    draft_key: SecretStr


class DraftTurn(DraftKey):
    action: Literal["read", "reply", "location", "animal", "retry"] = "read"
    text: str = Field(default="", max_length=4000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    number: int = Field(default=1, ge=1, le=100)


class PhoneToken(PrivateBody):
    id_token: SecretStr


class Submission(DraftKey, PhoneToken):
    contact_channels: list[Literal["call", "text"]] = Field(default_factory=list, max_length=2)


class Presence(PhoneToken):
    presence: Literal["nearby", "left", "unspecified"]


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def draft_access(session, incident_id, key, *, allow_submitted=False):
    value = key.get_secret_value()
    row = session.get(ReporterDraftRow, incident_id)
    if (
        not row
        or not 20 <= len(value) <= 128
        or not hmac.compare_digest(row.key_hash, digest(value))
        or row.expires_at <= datetime.now(UTC).replace(tzinfo=None)
        or (row.submitted_at is not None and not allow_submitted)
    ):
        raise HTTPException(404, "Draft unavailable")
    return row


def phone_account(session, body, *, recent=False):
    value = body.id_token.get_secret_value()
    if not settings.firebase_auth_project_id:
        raise HTTPException(503, "Phone sign-in verification is not configured")
    if not value or len(value) > 8192:
        raise HTTPException(401, "Verify your phone number")
    try:
        identity = verify_provider_token(value, settings.firebase_auth_project_id)
    except InvalidIdentity as exc:
        raise HTTPException(401, "Verify your phone number again") from exc
    except IdentityUnavailable as exc:
        raise HTTPException(503, "Phone verification is temporarily unavailable") from exc
    if (
        identity.sign_in_provider != "phone"
        or not identity.phone_number
        or not re.fullmatch(r"\+[1-9][0-9]{7,14}", identity.phone_number)
    ):
        raise HTTPException(403, "Verified phone sign-in required")
    age = datetime.now(UTC).timestamp() - (identity.auth_time or 0)
    if recent and not -60 <= age <= 900:
        raise HTTPException(401, "Verify your phone number again before submitting")
    try:
        user = ensure_account(session, identity)
    except AccessDenied as exc:
        raise HTTPException(403, "Account unavailable") from exc
    return user, identity


def own_submission(session, incident_id, body):
    user, _ = phone_account(session, body)
    row = session.get(ReporterDraftRow, incident_id)
    access = session.get(NetworkCaseRow, incident_id)
    if (
        not row
        or not row.submitted_at
        or row.submitted_user_id != user.user_id
        or not access
        or not access.submitted
        or access.reporter_user_id != user.user_id
    ):
        raise HTTPException(404, "Report unavailable")
    return row, user


@router.post("/drafts")
def start_draft(session: Session = Depends(get_session)):
    turn = intake.start_intake(intake.StartRequest(), session)
    key = secrets.token_urlsafe(32)
    row = ReporterDraftRow(
        incident_id=turn.incident_id,
        key_hash=digest(key),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24),
    )
    session.add(row)
    session.commit()
    return {
        "turn": private_turn(turn),
        "draft_key": key,
        "expires_at": row.expires_at.isoformat() + "Z",
    }


def private_turn(turn):
    # Draft readiness is not submission/acceptance. Never present suggested teams
    # or unprotected legacy photo URLs as a dispatch or a private media endpoint.
    result = turn.model_dump(mode="json")
    result["matched_teams"] = []
    result["detection_photo_url"] = None
    result["closing_note"] = (
        "Draft ready. Verify your phone to submit." if turn.complete else None
    )
    return result


@router.post("/drafts/{incident_id}/turn")
def draft_turn(incident_id: str, body: DraftTurn, session: Session = Depends(get_session)):
    draft_access(session, incident_id, body.draft_key)
    state = repository.load_conversation_state(session, incident_id)
    if body.action != "read" and state and state.stage == ConversationStage.COMPLETE:
        raise HTTPException(409, "Draft is ready to submit")
    if body.action == "reply":
        turn = intake.submit_reply(incident_id, intake.ReplyRequest(text=body.text), session)
    elif body.action == "location":
        if body.latitude is None or body.longitude is None:
            raise HTTPException(422, "Animal location required")
        turn = intake.set_location(
            incident_id,
            intake.LocationRequest(
                latitude=body.latitude, longitude=body.longitude, source="map_pin"
            ),
            session,
        )
    elif body.action == "animal":
        turn = intake.choose_animal(
            incident_id, intake.AnimalChoiceRequest(number=body.number), session
        )
    elif body.action == "retry":
        turn = intake.retry_step(incident_id, session)
    else:
        turn = intake.get_state(incident_id, session)
    return private_turn(turn)


@router.post("/drafts/{incident_id}/photo")
async def photo(
    incident_id: str,
    draft_key: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    draft_access(session, incident_id, SecretStr(draft_key))
    data = await file.read(intake.MAX_PHOTO_BYTES + 1)
    if len(data) > intake.MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo too large")
    await file.seek(0)
    return private_turn(await intake.upload_photo(incident_id, file, session))


@router.post("/drafts/{incident_id}/submit")
def submit(incident_id: str, body: Submission, session: Session = Depends(get_session)):
    row = draft_access(session, incident_id, body.draft_key, allow_submitted=True)
    user, identity = phone_account(session, body, recent=True)
    # Idempotent retries by the same verified subject only. Never reclaim by number.
    if row.submitted_at:
        if row.submitted_user_id != user.user_id:
            raise HTTPException(404, "Draft unavailable")
        return {"case_id": incident_id, "submitted": True}
    state = repository.load_conversation_state(session, incident_id)
    if not state or state.stage != ConversationStage.COMPLETE:
        raise HTTPException(409, "Finish the report before submitting")
    changed = session.execute(
        update(ReporterDraftRow)
        .where(
            ReporterDraftRow.incident_id == incident_id,
            ReporterDraftRow.submitted_at.is_(None),
        )
        .values(
            submitted_user_id=user.user_id,
            submitted_at=datetime.now(UTC).replace(tzinfo=None),
            phone_number=identity.phone_number,
            contact_channels=sorted(set(body.contact_channels)),
            contact_notice_version="current-case-v1",
        )
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Report submission changed; check its status")
    session.add(
        NetworkCaseRow(
            incident_id=incident_id,
            reporter_user_id=user.user_id,
            submitted=True,
            response_phase="received",
        )
    )
    # State/organization verification remains separate. Nothing here grants
    # professional memberships, assigns a center, or sends rescue notifications.
    session.commit()
    return {"case_id": incident_id, "submitted": True}


@router.post("/reports")
def reports(body: PhoneToken, session: Session = Depends(get_session)):
    user, _ = phone_account(session, body)
    rows = session.scalars(
        select(ReporterDraftRow)
        .join(NetworkCaseRow, NetworkCaseRow.incident_id == ReporterDraftRow.incident_id)
        .where(
            NetworkCaseRow.submitted.is_(True),
            NetworkCaseRow.reporter_user_id == user.user_id,
            ReporterDraftRow.submitted_user_id == user.user_id,
            ReporterDraftRow.submitted_at.is_not(None),
        )
        .order_by(ReporterDraftRow.submitted_at.desc())
        .limit(100)
    ).all()
    return [
        {"case_id": row.incident_id, "submitted_at": row.submitted_at.isoformat() + "Z"}
        for row in rows
    ]


@router.post("/reports/{incident_id}/status")
def status(incident_id: str, body: PhoneToken, session: Session = Depends(get_session)):
    row, user = own_submission(session, incident_id, body)
    access = session.get(NetworkCaseRow, incident_id)
    # Only reviewed response phases can advance the reporter's timeline. Raw AI
    # output, an old assignment or a guessed ETA cannot assert team acceptance.
    phase = ResponsePhase.RECEIVED
    if access and access.submitted and access.verified_at and access.verified_by:
        try:
            phase = ResponsePhase(access.response_phase)
        except ValueError as exc:
            raise HTTPException(409, "Case update unavailable") from exc
    return reporter_update(
        Principal(user.user_id, Role.REPORTER, identity_verified=True),
        CaseAccess(
            incident_id,
            reporter_user_id=user.user_id,
            submitted=True,
            active=phase != ResponsePhase.CLOSED,
        ),
        phase,
        now=datetime.now(UTC),
    ) | {"presence": row.presence}


@router.post("/reports/{incident_id}/presence")
def presence(incident_id: str, body: Presence, session: Session = Depends(get_session)):
    row, _ = own_submission(session, incident_id, body)
    row.presence = body.presence
    session.commit()
    return {"case_id": incident_id, "presence": row.presence, "leaving_cancels_report": False}


class ContactPreferences(PhoneToken):
    contact_channels: list[Literal["call", "text"]] = Field(default_factory=list, max_length=2)


@router.post("/reports/{incident_id}/contact-preferences")
def contact_preferences(
    incident_id: str, body: ContactPreferences, session: Session = Depends(get_session)
):
    row, user = own_submission(session, incident_id, body)
    row.contact_channels = sorted(set(body.contact_channels))
    row.contact_notice_version = "current-case-v1"
    audit(
        session,
        "reporter_contact_preferences_changed",
        incident_id,
        user.user_id,
        {"channels": row.contact_channels, "notice_version": "current-case-v1"},
    )
    session.commit()
    return {"case_id": incident_id, "contact_channels": row.contact_channels}
