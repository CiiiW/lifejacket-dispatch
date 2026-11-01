"""Offline reviewed case enrollment. No automatic legacy ownership/state backfill."""

import argparse

from lifejacket.access.case_review import review_case
from lifejacket.access.policy import US_STATES
from lifejacket.models.db import engine, session_scope
from lifejacket.models.tables import (
    NetworkCaseAssigneeRow,
    NetworkCaseOrganizationRow,
    NetworkCaseRow,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    review = commands.add_parser("review")
    review.add_argument("--case-id", required=True)
    review.add_argument("--state", required=True, choices=sorted(US_STATES))
    review.add_argument(
        "--owner-account",
        help=(
            "Legacy ownership binding, or the existing phone-report owner; "
            "cannot replace verified ownership"
        ),
    )
    review.add_argument(
        "--lead-organization",
        help="Approved lead center (required to review a submitted phone report)",
    )
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
