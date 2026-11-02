"""Verified managed identity -> current database memberships -> policy principal."""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from lifejacket.access.identity import (
    IdentityUnavailable,
    InvalidIdentity,
    VerifiedIdentity,
    verify_provider_token,
)
from lifejacket.access.memberships import AccessDenied, ResolvedAccess, resolve_access
from lifejacket.config import settings
from lifejacket.models.db import get_session

bearer = HTTPBearer(auto_error=False)


def authenticated_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> VerifiedIdentity:
    if not settings.network_auth_enabled or not settings.firebase_auth_project_id:
        raise HTTPException(503, "App sign-in is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Sign-in required", headers={"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    if not token or len(token) > 8192:
        raise HTTPException(
            401, "Invalid sign-in token", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        return verify_provider_token(token, settings.firebase_auth_project_id)
    except InvalidIdentity as exc:
        raise HTTPException(
            401, "Invalid sign-in token", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    except IdentityUnavailable as exc:
        raise HTTPException(503, "Sign-in verification is temporarily unavailable") from exc


@dataclass(frozen=True)
class AccessSession:
    identity: VerifiedIdentity
    access: ResolvedAccess


def current_access_session(
    identity: VerifiedIdentity = Depends(authenticated_identity),
    organization_id: str | None = Header(
        default=None,
        alias="X-LifeJacket-Organization",
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
    session: Session = Depends(get_session),
) -> AccessSession:
    try:
        access = resolve_access(session, identity, organization_id)
    except AccessDenied as exc:
        raise HTTPException(403, "Account or organization access is not approved") from exc
    return AccessSession(identity, access)
