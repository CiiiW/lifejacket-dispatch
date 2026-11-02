"""Deny-by-default network rules over server-verified identity and case snapshots.

This is NOT an authentication mechanism. Future adapters must derive snapshots
from verified sessions, memberships, geography, participation and consent records,
never deserialize Principal/CaseAccess directly from an HTTP request. Existing
legacy endpoints do not call this module yet and are NOT protected by it.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    NOAA = "noaa"
    CENTER_COORDINATOR = "center_coordinator"
    RESCUER = "rescuer"
    REPORTER = "reporter"
    VOLUNTEER = "volunteer"


US_STATES = frozenset(
    [
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
    ]
)


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: Role
    identity_verified: bool = False
    enabled: bool = True
    organization_id: str | None = None
    membership_verified: bool = False
    allowed_states: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CaseAccess:
    case_id: str
    reporter_user_id: str | None = None
    submitted: bool = False
    state_code: str | None = None
    state_verified: bool = False
    active: bool = True
    lead_org_id: str | None = None
    accepted_support_org_ids: frozenset[str] = field(default_factory=frozenset)
    confirmed_receiving_org_id: str | None = None
    accepted_assignee_user_ids: frozenset[str] = field(default_factory=frozenset)
    # Valid current-case permission, not a future-volunteering subscription.
    reporter_contact_channels: frozenset[str] = field(default_factory=frozenset)


def identity_valid(actor: Principal) -> bool:
    return bool(
        actor.enabled
        and actor.identity_verified
        and actor.user_id.strip()
        and isinstance(actor.role, Role)
    )


def owns_report(actor: Principal, case: CaseAccess) -> bool:
    return identity_valid(actor) and case.reporter_user_id == actor.user_id


def _member(actor: Principal) -> bool:
    return bool(identity_valid(actor) and actor.membership_verified and actor.organization_id)


def _in_state(actor: Principal, case: CaseAccess) -> bool:
    return bool(
        case.state_verified
        and case.state_code in US_STATES
        and case.state_code in actor.allowed_states
    )


def participating_org(actor: Principal, case: CaseAccess) -> bool:
    if not _member(actor):
        return False
    return actor.organization_id in (
        {case.lead_org_id, case.confirmed_receiving_org_id} | case.accepted_support_org_ids
    )


def can_view_professional_case(actor: Principal, case: CaseAccess) -> bool:
    if not _member(actor) or not case.submitted:
        return False
    if actor.role == Role.NOAA:
        return True
    if not _in_state(actor, case):
        return False
    if actor.role == Role.CENTER_COORDINATOR:
        return True
    if actor.role == Role.RESCUER:
        return (
            participating_org(actor, case) and actor.user_id in case.accepted_assignee_user_ids
        )
    return False


def can_view_report(actor: Principal, case: CaseAccess) -> bool:
    # An account that also works for a center may still view its own report.
    return owns_report(actor, case) or can_view_professional_case(actor, case)


def case_matches_filter(actor: Principal, case: CaseAccess, scope: str) -> bool:
    """Professional filters only narrow the professional visibility boundary."""
    if not can_view_professional_case(actor, case):
        return False
    if scope == "all_allowed":
        return True
    if scope == "my_center":
        return participating_org(actor, case)
    if scope == "assigned_to_me":
        return actor.user_id in case.accepted_assignee_user_ids
    if scope == "leading":
        return actor.organization_id == case.lead_org_id
    if scope == "supporting":
        return actor.organization_id in case.accepted_support_org_ids
    if scope == "receiving":
        return actor.organization_id == case.confirmed_receiving_org_id
    return False


def can_update_case(actor: Principal, case: CaseAccess) -> bool:
    return bool(
        case.active
        and can_view_professional_case(actor, case)
        and participating_org(actor, case)
        and actor.role in {Role.CENTER_COORDINATOR, Role.RESCUER}
    )


def can_contact_reporter(actor: Principal, case: CaseAccess, channel: str) -> bool:
    return (
        channel in {"phone", "text"}
        and channel in case.reporter_contact_channels
        and can_update_case(actor, case)
    )


def can_change_responsibility(actor: Principal, case: CaseAccess) -> bool:
    # NOAA operational override permissions have not been agreed: no implied override.
    return bool(
        can_update_case(actor, case)
        and actor.role == Role.CENTER_COORDINATOR
        and actor.organization_id == case.lead_org_id
    )


def can_update_own_availability(actor: Principal, case: CaseAccess) -> bool:
    return case.active and owns_report(actor, case)
