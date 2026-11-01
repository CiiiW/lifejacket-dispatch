"""Authenticated session identity; no self-service professional role grants."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from lifejacket.access.dependencies import AccessSession, current_access_session
from lifejacket.access.policy import Role

router = APIRouter(prefix="/access", tags=["verified app access"])


class OrganizationOption(BaseModel):
    organization_id: str
    name: str
    role: Role
    states: list[str]


class SessionView(BaseModel):
    account_id: str
    role: Role
    selected_organization_id: str | None
    authorized_states: list[str]
    email: str | None
    email_verified: bool
    organizations: list[OrganizationOption]


@router.get("/me", response_model=SessionView)
def who_am_i(response: Response, current: AccessSession = Depends(current_access_session)):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization, X-LifeJacket-Organization"
    principal = current.access.principal
    return SessionView(
        account_id=principal.user_id,
        role=principal.role,
        selected_organization_id=principal.organization_id,
        authorized_states=sorted(principal.allowed_states),
        email=current.identity.email,
        email_verified=current.identity.email_verified,
        organizations=list(current.access.organization_options),
    )
