"""Trusted offline organization approval; never a public self-enrollment API.

Provision professional access only after verifying an actual account/organization
and the person's authority. This command stores no passwords or bearer tokens.
"""

import argparse

from lifejacket.access.memberships import (
    AccessDenied,
    approve_membership,
    approve_organization,
    revoke_membership,
)
from lifejacket.models.db import engine, session_scope
from lifejacket.models.tables import (
    AccessAuditRow,
    AccessMembershipRow,
    AccessOrganizationRow,
    AccessUserRow,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "init", help="Create only additive access tables; no existing rows changed"
    )
    org = commands.add_parser("approve-organization")
    org.add_argument("--id", required=True)
    org.add_argument("--name", required=True)
    org.add_argument("--kind", required=True, choices=["noaa", "rescue_center"])
    org.add_argument("--states", nargs="*", default=[])
    org.add_argument("--verified-by", required=True)
    member = commands.add_parser("approve-member")
    member.add_argument("--account-id", required=True)
    member.add_argument("--organization-id", required=True)
    member.add_argument(
        "--role", required=True, choices=["noaa", "center_coordinator", "rescuer"]
    )
    member.add_argument("--states", nargs="*", default=[])
    member.add_argument("--verified-by", required=True)
    revoke = commands.add_parser("revoke-member")
    revoke.add_argument("--membership-id", required=True)
    revoke.add_argument("--verified-by", required=True)
    args = parser.parse_args()
    if args.command == "init":
        for table in [
            AccessUserRow,
            AccessOrganizationRow,
            AccessMembershipRow,
            AccessAuditRow,
        ]:
            table.__table__.create(engine, checkfirst=True)
        print("Access tables ready. No accounts or professional memberships granted.")
        return
    try:
        with session_scope() as session:
            if args.command == "approve-organization":
                row = approve_organization(
                    session, args.id, args.name, args.kind, args.states, args.verified_by
                )
                print("Approved organization:", row.organization_id)
            elif args.command == "approve-member":
                row = approve_membership(
                    session,
                    args.account_id,
                    args.organization_id,
                    args.role,
                    args.states,
                    args.verified_by,
                )
                print("Approved membership:", row.membership_id)
            else:
                row = revoke_membership(session, args.membership_id, args.verified_by)
                print("Revoked membership:", row.membership_id)
    except (AccessDenied, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Access approval failed: {exc}\n")


if __name__ == "__main__":
    main()
