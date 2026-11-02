"""Trusted offline case review; never a public self-service scope/ownership grant."""

import re
from datetime import UTC, datetime

from sqlalchemy import exists, select, update

from lifejacket.access.memberships import _admin_ref, audit
from lifejacket.access.policy import US_STATES
from lifejacket.models.tables import (
    AccessOrganizationRow,
    AccessUserRow,
    IncidentRow,
    NetworkCaseAssigneeRow,
    NetworkCaseOrganizationRow,
    NetworkCaseRow,
    NetworkResponseEventRow,
    NetworkResponseRow,
    ReporterDraftRow,
)


def _lead(session, organization_id, state):
    if organization_id is None:
        return
    org = session.get(AccessOrganizationRow, organization_id)
    if (
        not org
        or not org.enabled
        or org.kind != "rescue_center"
        or not org.verified_at
        or not org.verified_by
        or not org.verified_by.strip()
        or state not in (org.approved_states or [])
    ):
        raise ValueError("Lead center must be approved for this state")


def _owner(session, owner_id):
    if owner_id is None:
        return
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("Use an existing enabled account after verifying report ownership")
    user = session.get(AccessUserRow, owner_id)
    if not user or not user.enabled:
        raise ValueError("Use an existing enabled account after verifying report ownership")


def _no_operations(case_id):
    return [
        ~exists(select(1).where(model.incident_id == case_id))
        for model in [
            NetworkCaseOrganizationRow,
            NetworkCaseAssigneeRow,
            NetworkResponseRow,
            NetworkResponseEventRow,
        ]
    ]


def review_case(session, case_id, state, owner, lead, verified_by):
    """Enroll legacy cases, or complete first review of a pristine submitted phone case.

    State and lead are reviewed operator inputs. Existing ownership is immutable.
    Already reviewed/operational or partially populated scopes need a distinct
    correction/reassignment workflow; this command cannot be used to reset them.
    """
    reviewer = _admin_ref(verified_by)
    if state not in US_STATES:
        raise ValueError("Use a reviewed US state code")
    if not session.get(IncidentRow, case_id):
        raise ValueError("Incident not found")
    row = session.get(NetworkCaseRow, case_id)
    draft = session.get(ReporterDraftRow, case_id)
    _lead(session, lead, state)
    now = datetime.now(UTC).replace(tzinfo=None)

    if row is None:
        if draft is not None:
            raise ValueError(
                "Phone reports must be submitted with intact ownership metadata before review"
            )
        _owner(session, owner)
        row = NetworkCaseRow(
            incident_id=case_id,
            reporter_user_id=owner,
            submitted=True,
            state_code=state,
            verified_at=now,
            verified_by=reviewer,
            lead_org_id=lead,
            response_phase="received",
        )
        session.add(row)
        path = "legacy_enrollment"
    else:
        if (
            not row.submitted
            or row.verified_at is not None
            or row.verified_by is not None
            or row.state_code is not None
            or row.lead_org_id is not None
            or row.response_phase != "received"
        ):
            raise ValueError(
                "Case already reviewed or changed; use a separate correction workflow"
            )
        bound_owner = row.reporter_user_id
        if (
            not draft
            or not draft.submitted_at
            or not bound_owner
            or draft.submitted_user_id != bound_owner
            or not draft.phone_number
            or not re.fullmatch(r"\+[1-9][0-9]{7,14}", draft.phone_number)
        ):
            raise ValueError(
                "Submitted phone-report ownership needs review; no scope was granted"
            )
        if owner is not None and owner != bound_owner:
            raise ValueError("Cannot replace verified reporter ownership during case review")
        _owner(session, bound_owner)
        if lead is None:
            raise ValueError("Choose an approved lead center for this submitted phone report")
        untouched = _no_operations(case_id)
        if not session.scalar(
            select(NetworkCaseRow.incident_id).where(
                NetworkCaseRow.incident_id == case_id,
                *untouched,
            )
        ):
            raise ValueError(
                "Case already has operational metadata; use a separate correction workflow"
            )
        # Compare-and-set prevents a second operator overwriting a concurrent review.
        changed = session.execute(
            update(NetworkCaseRow)
            .where(
                NetworkCaseRow.incident_id == case_id,
                NetworkCaseRow.submitted.is_(True),
                NetworkCaseRow.reporter_user_id == bound_owner,
                NetworkCaseRow.verified_at.is_(None),
                NetworkCaseRow.verified_by.is_(None),
                NetworkCaseRow.state_code.is_(None),
                NetworkCaseRow.lead_org_id.is_(None),
                NetworkCaseRow.response_phase == "received",
                *untouched,
                exists(
                    select(1).where(
                        ReporterDraftRow.incident_id == case_id,
                        ReporterDraftRow.submitted_at.is_not(None),
                        ReporterDraftRow.submitted_user_id == bound_owner,
                        ReporterDraftRow.phone_number == draft.phone_number,
                    )
                ),
            )
            .values(state_code=state, lead_org_id=lead, verified_at=now, verified_by=reviewer),
            execution_options={"synchronize_session": False},
        )
        if changed.rowcount != 1:
            session.rollback()
            raise ValueError("Case changed while being reviewed; reload before trying again")
        session.refresh(row)
        path = "submitted_phone_report"
    audit(
        session,
        "network_case_reviewed",
        case_id,
        reviewer,
        {
            "state": state,
            "owner_account_id": row.reporter_user_id,
            "lead_organization_id": lead,
            "review_path": path,
        },
    )
    session.commit()
    return row
