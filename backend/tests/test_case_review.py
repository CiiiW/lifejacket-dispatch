from datetime import datetime, timedelta

import pytest
from lifejacket.access.case_review import review_case
from lifejacket.models.tables import (
    AccessAuditRow,
    AccessOrganizationRow,
    AccessUserRow,
    Base,
    IncidentRow,
    NetworkCaseAssigneeRow,
    NetworkCaseOrganizationRow,
    NetworkCaseRow,
    NetworkResponseEventRow,
    NetworkResponseRow,
    ReporterDraftRow,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(
            IncidentRow(incident_id="case", status="awaiting_dispatch", report_json={})
        )
        session.add(
            AccessUserRow(user_id="owner", issuer="fixture", subject="reporter", enabled=True)
        )
        session.add(
            AccessOrganizationRow(
                organization_id="A",
                name="Fixture center",
                kind="rescue_center",
                enabled=True,
                approved_states=["CA"],
                verified_at=datetime.now(),
                verified_by="admin",
            )
        )
        session.add(
            NetworkCaseRow(
                incident_id="case",
                reporter_user_id="owner",
                submitted=True,
                response_phase="received",
            )
        )
        session.add(
            ReporterDraftRow(
                incident_id="case",
                key_hash="x" * 64,
                expires_at=datetime.now() - timedelta(days=1),
                submitted_user_id="owner",
                submitted_at=datetime.now(),
                phone_number="+12025550123",
                contact_channels=["text"],
                contact_notice_version="v1",
                presence="left",
            )
        )
        session.commit()
    yield factory
    engine.dispose()


@pytest.mark.parametrize("owner", [None, "owner"])
def test_review_preserves_verified_owner_contact_consent_and_phase(factory, owner):
    # Submitted reports remain reviewable after their private draft key expires.
    with factory() as session:
        row = review_case(session, "case", "CA", owner, "A", "reviewer")
        assert (row.reporter_user_id, row.state_code, row.lead_org_id, row.response_phase) == (
            "owner",
            "CA",
            "A",
            "received",
        )
        draft = session.get(ReporterDraftRow, "case")
        assert draft.contact_channels == ["text"] and draft.presence == "left"
        assert draft.phone_number == "+12025550123" and draft.contact_notice_version == "v1"
        event = session.scalars(select(AccessAuditRow)).one()
        assert event.kind == "network_case_reviewed" and event.actor_ref == "reviewer"
        assert event.details["review_path"] == "submitted_phone_report"
        assert "+12025550123" not in str(event.details)
        with pytest.raises(ValueError):
            review_case(session, "case", "CA", None, "A", "second-reviewer")
        assert len(session.scalars(select(AccessAuditRow)).all()) == 1


@pytest.mark.parametrize(
    "change",
    [
        "other_owner",
        "missing_owner",
        "disabled_owner",
        "missing_draft",
        "draft_owner",
        "draft_unsubmitted",
        "bad_phone",
        "unsubmitted",
        "state",
        "lead",
        "verified_at",
        "verified_by",
        "advanced",
        "support",
        "assignee",
        "revision",
        "event",
        "no_lead",
        "disabled_lead",
        "unverified_lead",
        "wrong_state",
        "noaa_lead",
        "invalid_state",
    ],
)
def test_review_rejects_inconsistent_or_operational_reports_without_grant(factory, change):
    with factory() as session:
        scope = session.get(NetworkCaseRow, "case")
        draft = session.get(ReporterDraftRow, "case")
        lead = session.get(AccessOrganizationRow, "A")
        owner_arg, lead_arg, state = None, "A", "CA"
        if change == "other_owner":
            owner_arg = "somebody-else"
        elif change == "missing_owner":
            scope.reporter_user_id = None
        elif change == "disabled_owner":
            session.get(AccessUserRow, "owner").enabled = False
        elif change == "missing_draft":
            session.delete(draft)
        elif change == "draft_owner":
            draft.submitted_user_id = None
        elif change == "draft_unsubmitted":
            draft.submitted_at = None
        elif change == "bad_phone":
            draft.phone_number = "invalid"
        elif change == "unsubmitted":
            scope.submitted = False
        elif change == "state":
            scope.state_code = "CA"
        elif change == "lead":
            scope.lead_org_id = "A"
        elif change == "verified_at":
            scope.verified_at = datetime.now()
        elif change == "verified_by":
            scope.verified_by = ""
        elif change == "advanced":
            scope.response_phase = "accepted"
        elif change == "support":
            session.add(
                NetworkCaseOrganizationRow(
                    incident_id="case", organization_id="A", kind="supporting", accepted=False
                )
            )
        elif change == "assignee":
            session.add(
                NetworkCaseAssigneeRow(
                    incident_id="case", organization_id="A", user_id="owner", accepted=False
                )
            )
        elif change == "revision":
            session.add(NetworkResponseRow(incident_id="case", revision=0))
        elif change == "event":
            session.add(
                NetworkResponseEventRow(
                    event_id="e",
                    incident_id="case",
                    revision=1,
                    previous_phase="received",
                    phase="accepted",
                    actor_user_id="owner",
                    organization_id="A",
                )
            )
        elif change == "no_lead":
            lead_arg = None
        elif change == "disabled_lead":
            lead.enabled = False
        elif change == "unverified_lead":
            lead.verified_by = " "
        elif change == "wrong_state":
            lead.approved_states = ["OR"]
        elif change == "noaa_lead":
            lead.kind = "noaa"
        elif change == "invalid_state":
            state = "XX"
        session.commit()
        original = (
            scope.reporter_user_id,
            scope.state_code,
            scope.lead_org_id,
            scope.response_phase,
        )
        with pytest.raises(ValueError):
            review_case(session, "case", state, owner_arg, lead_arg, "reviewer")
        session.refresh(scope)
        assert (
            scope.reporter_user_id,
            scope.state_code,
            scope.lead_org_id,
            scope.response_phase,
        ) == original
        assert session.scalars(select(AccessAuditRow)).all() == []


def test_legacy_enrollment_and_phone_draft_bypass(factory):
    with factory() as session:
        session.delete(session.get(NetworkCaseRow, "case"))
        session.commit()
        with pytest.raises(ValueError, match="must be submitted"):
            review_case(session, "case", "CA", "owner", None, "reviewer")
        session.delete(session.get(ReporterDraftRow, "case"))
        session.commit()
        row = review_case(session, "case", "CA", "owner", None, "reviewer")
        assert row.reporter_user_id == "owner" and row.submitted
        assert (
            session.scalars(select(AccessAuditRow)).one().details["review_path"]
            == "legacy_enrollment"
        )


def test_stale_reviewer_cannot_overwrite_winning_review(factory):
    with factory() as stale:
        held = stale.get(NetworkCaseRow, "case")
        with factory() as winner:
            review_case(winner, "case", "CA", None, "A", "first")
        assert held.verified_at is None
        with pytest.raises(ValueError, match="changed while"):
            review_case(stale, "case", "CA", None, "A", "second")
    with factory() as session:
        assert session.get(NetworkCaseRow, "case").verified_by == "first"
        assert len(session.scalars(select(AccessAuditRow)).all()) == 1
