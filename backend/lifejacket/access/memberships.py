"""Persistent, explicit professional access; sign-in creates a personal account only."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lifejacket.access.identity import VerifiedIdentity
from lifejacket.access.policy import US_STATES, Principal, Role
from lifejacket.models.tables import (
    AccessAuditRow,
    AccessMembershipRow,
    AccessOrganizationRow,
    AccessUserRow,
)


class AccessDenied(Exception):
    pass


def _id(prefix):
    return prefix + uuid.uuid4().hex


def audit(session, kind, target, actor, details):
    session.add(
        AccessAuditRow(
            event_id=_id("evt_"), kind=kind, target_id=target, actor_ref=actor, details=details
        )
    )


def ensure_account(session, identity: VerifiedIdentity):
    user = session.scalar(
        select(AccessUserRow).where(
            AccessUserRow.issuer == identity.issuer, AccessUserRow.subject == identity.subject
        )
    )
    if user is None:
        user = AccessUserRow(
            user_id=_id("usr_"), issuer=identity.issuer, subject=identity.subject, enabled=True
        )
        session.add(user)
        audit(
            session,
            "personal_account_created",
            user.user_id,
            user.user_id,
            {"professional_access": False},
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            user = session.scalar(
                select(AccessUserRow).where(
                    AccessUserRow.issuer == identity.issuer,
                    AccessUserRow.subject == identity.subject,
                )
            )
            if user is None:
                raise
    if not user.enabled:
        raise AccessDenied("Account is disabled")
    return user


def _states(value):
    if not isinstance(value, list) or any(
        not isinstance(s, str) or s not in US_STATES for s in value
    ):
        raise AccessDenied("Organization state scope needs review")
    return frozenset(value)


def membership_context(session, user_id, organization_id):
    org = session.get(AccessOrganizationRow, organization_id)
    member = session.scalar(
        select(AccessMembershipRow).where(
            AccessMembershipRow.user_id == user_id,
            AccessMembershipRow.organization_id == organization_id,
        )
    )
    if (
        not org
        or not org.enabled
        or not org.verified_at
        or not org.verified_by
        or not member
        or member.status != "active"
        or not member.verified_at
        or not member.verified_by
    ):
        raise AccessDenied("Organization membership is not approved")
    try:
        role = Role(member.role)
    except ValueError as exc:
        raise AccessDenied("Membership role needs review") from exc
    org_states, member_states = _states(org.approved_states), _states(member.approved_states)
    if org.kind == "noaa" and role == Role.NOAA:
        if org_states or member_states:
            raise AccessDenied("NOAA membership scope needs review")
        states = frozenset()
    elif org.kind == "rescue_center" and role in {Role.CENTER_COORDINATOR, Role.RESCUER}:
        if not member_states or not member_states.issubset(org_states):
            raise AccessDenied("Membership state scope is not approved")
        states = member_states
    else:
        raise AccessDenied("Role is incompatible with the organization")
    return org, member, role, states


@dataclass(frozen=True)
class ResolvedAccess:
    principal: Principal
    organization_options: tuple[dict, ...]


def resolve_access(session, identity: VerifiedIdentity, organization_id=None):
    user = ensure_account(session, identity)
    options = []
    if identity.email_verified:
        memberships = session.scalars(
            select(AccessMembershipRow).where(AccessMembershipRow.user_id == user.user_id)
        ).all()
        for membership in memberships:
            try:
                org, _, role, states = membership_context(
                    session, user.user_id, membership.organization_id
                )
            except AccessDenied:
                continue
            options.append(
                {
                    "organization_id": org.organization_id,
                    "name": org.name,
                    "role": role.value,
                    "states": sorted(states),
                }
            )
    if organization_id is None:
        principal = Principal(user.user_id, Role.REPORTER, identity_verified=True)
    else:
        if not identity.email_verified:
            raise AccessDenied("Verified email is required for professional access")
        org, _, role, states = membership_context(session, user.user_id, organization_id)
        principal = Principal(
            user.user_id,
            role,
            identity_verified=True,
            organization_id=org.organization_id,
            membership_verified=True,
            allowed_states=states,
        )
    return ResolvedAccess(principal, tuple(options))


def _admin_ref(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
        raise ValueError("Record an approving administrator of 1 to 80 characters")
    return value.strip()


def approve_organization(session, org_id, name, kind, states, verified_by):
    """Trusted offline admin operation, never exposed as a self-service HTTP grant."""
    verified_by = _admin_ref(verified_by)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", org_id) or not 1 <= len(name.strip()) <= 256:
        raise ValueError("Provide a safe organization ID and name")
    if kind not in {"noaa", "rescue_center"}:
        raise ValueError("Unsupported organization kind")
    approved = _states(states)
    if (kind == "noaa" and approved) or (kind == "rescue_center" and not approved):
        raise ValueError("Provide explicit state scope for a rescue center only")
    row = session.get(AccessOrganizationRow, org_id)
    if row is not None:
        raise ValueError("Organization exists; use a reviewed scope-change workflow")
    row = AccessOrganizationRow(
        organization_id=org_id,
        name=name.strip(),
        kind=kind,
        enabled=True,
        approved_states=sorted(approved),
        verified_at=datetime.now(UTC).replace(tzinfo=None),
        verified_by=verified_by.strip(),
    )
    session.add(row)
    audit(
        session,
        "organization_approved",
        org_id,
        verified_by.strip(),
        {"kind": kind, "states": sorted(approved)},
    )
    session.commit()
    return row


def approve_membership(session, user_id, org_id, role, states, verified_by):
    verified_by = _admin_ref(verified_by)
    user, org = session.get(AccessUserRow, user_id), session.get(AccessOrganizationRow, org_id)
    if not user or not user.enabled or not org or not org.enabled or not org.verified_at:
        raise ValueError("Use an existing verified account and approved organization")
    if session.scalar(
        select(AccessMembershipRow).where(
            AccessMembershipRow.user_id == user_id,
            AccessMembershipRow.organization_id == org_id,
        )
    ):
        raise ValueError("Membership already exists")
    member = AccessMembershipRow(
        membership_id=_id("mem_"),
        user_id=user_id,
        organization_id=org_id,
        role=Role(role).value,
        status="active",
        approved_states=sorted(_states(states)),
        verified_at=datetime.now(UTC).replace(tzinfo=None),
        verified_by=verified_by.strip(),
    )
    session.add(member)
    session.flush()
    try:
        membership_context(session, user_id, org_id)
    except AccessDenied as exc:
        session.rollback()
        raise ValueError(str(exc)) from exc
    audit(
        session,
        "membership_approved",
        member.membership_id,
        verified_by.strip(),
        {
            "user_id": user_id,
            "organization_id": org_id,
            "role": member.role,
            "states": member.approved_states,
        },
    )
    session.commit()
    return member


def revoke_membership(session, membership_id, verified_by):
    verified_by = _admin_ref(verified_by)
    member = session.get(AccessMembershipRow, membership_id)
    if not member:
        raise ValueError("Membership not found")
    if member.status != "revoked":
        member.status = "revoked"
        audit(session, "membership_revoked", membership_id, verified_by.strip(), {})
        session.commit()
    return member
