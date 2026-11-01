"""Offline reviewed case enrollment. No automatic legacy ownership/state backfill."""

import argparse
from datetime import UTC, datetime

from lifejacket.access.memberships import _admin_ref, audit
from lifejacket.access.policy import US_STATES
from lifejacket.models.db import engine, session_scope
from lifejacket.models.tables import (
    AccessOrganizationRow,
    AccessUserRow,
    IncidentRow,
    NetworkCaseAssigneeRow,
    NetworkCaseOrganizationRow,
    NetworkCaseRow,
)


def review_case(session, case_id, state, owner, lead, verified_by):
    reviewer = _admin_ref(verified_by)
    if state not in US_STATES:
        raise ValueError("Use a reviewed US state code")
    if not session.get(IncidentRow, case_id):
        raise ValueError("Incident not found")
    if session.get(NetworkCaseRow, case_id):
        raise ValueError("Case already enrolled; changes require a separate reviewed workflow")
    if owner:
        user = session.get(AccessUserRow, owner)
        if not user or not user.enabled:
            raise ValueError(
                "Use an existing enabled account after verifying report ownership"
            )
    if lead:
        org = session.get(AccessOrganizationRow, lead)
        if (
            not org
            or not org.enabled
            or org.kind != "rescue_center"
            or not org.verified_at
            or not org.verified_by
            or state not in (org.approved_states or [])
        ):
            raise ValueError("Lead center must be approved for this state")
    row = NetworkCaseRow(
        incident_id=case_id,
        reporter_user_id=owner,
        submitted=True,
        state_code=state,
        verified_at=datetime.now(UTC).replace(tzinfo=None),
        verified_by=reviewer,
        lead_org_id=lead,
        response_phase="received",
    )
    session.add(row)
    audit(
        session,
        "network_case_reviewed",
        case_id,
        reviewer,
        {"state": state, "owner_account_id": owner, "lead_organization_id": lead},
    )
    session.commit()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    review = commands.add_parser("review")
    review.add_argument("--case-id", required=True)
    review.add_argument("--state", required=True, choices=sorted(US_STATES))
    review.add_argument("--owner-account")
    review.add_argument("--lead-organization")
    review.add_argument("--verified-by", required=True)
    review.add_argument(
        "--confirmed-submitted",
        action="store_true",
        required=True,
        help="Attest this is a submitted report; do not enroll test/demo evidence",
    )
    args = parser.parse_args()
    if args.command == "init":
        for model in [NetworkCaseRow, NetworkCaseOrganizationRow, NetworkCaseAssigneeRow]:
            model.__table__.create(engine, checkfirst=True)
        print("Network case tables ready; no cases enrolled or assignments granted.")
        return
    try:
        with session_scope() as session:
            row = review_case(
                session,
                args.case_id,
                args.state,
                args.owner_account,
                args.lead_organization,
                args.verified_by,
            )
            print("Reviewed submitted case:", row.incident_id)
    except ValueError as exc:
        parser.exit(1, f"Case review failed: {exc}\n")


if __name__ == "__main__":
    main()
