"""Database scope for the restricted network read API. Legacy metadata grants nothing."""

from sqlalchemy import exists, or_, select

from lifejacket.access.policy import US_STATES, CaseAccess, Role
from lifejacket.models.tables import (
    IncidentRow,
)
from lifejacket.models.tables import (
    NetworkCaseAssigneeRow as Assignee,
)
from lifejacket.models.tables import (
    NetworkCaseOrganizationRow as Organization,
)
from lifejacket.models.tables import (
    NetworkCaseRow as Scope,
)

FILTERS = {"all_allowed", "my_center", "assigned_to_me", "leading", "supporting", "receiving"}


def organization_relation(actor, kind=None):
    criteria = [
        Organization.incident_id == Scope.incident_id,
        Organization.organization_id == actor.organization_id,
        Organization.accepted.is_(True),
        Organization.kind.in_(["supporting", "receiving"]),
    ]
    if kind:
        criteria.append(Organization.kind == kind)
    return exists(select(1).where(*criteria))


def participating(actor):
    return or_(Scope.lead_org_id == actor.organization_id, organization_relation(actor))


def assigned(actor):
    return exists(
        select(1).where(
            Assignee.incident_id == Scope.incident_id,
            Assignee.user_id == actor.user_id,
            Assignee.organization_id == actor.organization_id,
            Assignee.accepted.is_(True),
        )
    )


def professional_query(actor, scope_filter="all_allowed"):
    query = select(IncidentRow, Scope).join(
        Scope, Scope.incident_id == IncidentRow.incident_id
    )
    if (
        not actor.identity_verified
        or not actor.enabled
        or not actor.membership_verified
        or not actor.organization_id
        or scope_filter not in FILTERS
    ):
        return query.where(False)
    query = query.where(Scope.submitted.is_(True))
    if actor.role != Role.NOAA:
        query = query.where(
            Scope.state_code.in_(actor.allowed_states & US_STATES),
            Scope.verified_at.is_not(None),
            Scope.verified_by.is_not(None),
            Scope.verified_by != "",
        )
        if actor.role == Role.RESCUER:
            query = query.where(participating(actor), assigned(actor))
        elif actor.role != Role.CENTER_COORDINATOR:
            return query.where(False)
    if scope_filter == "my_center":
        query = query.where(participating(actor))
    elif scope_filter == "assigned_to_me":
        query = query.where(assigned(actor))
    elif scope_filter == "leading":
        query = query.where(Scope.lead_org_id == actor.organization_id)
    elif scope_filter == "supporting":
        query = query.where(organization_relation(actor, "supporting"))
    elif scope_filter == "receiving":
        query = query.where(organization_relation(actor, "receiving"))
    return query


def reporter_case(actor, row):
    return CaseAccess(
        case_id=row.incident_id,
        reporter_user_id=row.reporter_user_id,
        submitted=row.submitted,
        active=row.response_phase != "closed",
    )


def case_card(incident, access):
    # Enumerated fields only. No free text, reporter contact, staff positions,
    # transcripts, raw reports, duplicate links or global aggregates.
    return {
        "incident_id": incident.incident_id,
        "status": incident.status,
        "state_code": access.state_code
        if access.verified_at and access.verified_by and access.state_code in US_STATES
        else None,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "animal_group": incident.animal_group,
        "species_common_name": incident.species_common_name,
        "severity_level": incident.severity_level,
        "lead_organization_id": access.lead_org_id,
        "created_at": incident.created_at,
    }
