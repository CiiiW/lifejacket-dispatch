from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from lifejacket.access.policy import (
    CaseAccess,
    Principal,
    Role,
    can_change_responsibility,
    can_contact_reporter,
    can_update_case,
    can_update_own_availability,
    can_view_professional_case,
    can_view_report,
    case_matches_filter,
)
from lifejacket.access.reporter_view import ArrivalEstimate, ResponsePhase, reporter_update

CASE = CaseAccess(
    "case",
    reporter_user_id="reporter",
    submitted=True,
    state_code="CA",
    state_verified=True,
    lead_org_id="A",
    accepted_support_org_ids=frozenset({"B"}),
    confirmed_receiving_org_id="C",
    accepted_assignee_user_ids=frozenset({"field-a"}),
    reporter_contact_channels=frozenset({"phone"}),
)
COORD = Principal(
    "coord",
    Role.CENTER_COORDINATOR,
    identity_verified=True,
    organization_id="A",
    membership_verified=True,
    allowed_states=frozenset({"CA"}),
)
NOAA = replace(
    COORD, user_id="noaa", role=Role.NOAA, organization_id="NOAA", allowed_states=frozenset()
)
FIELD = replace(COORD, user_id="field-a", role=Role.RESCUER)
REPORTER = Principal("reporter", Role.REPORTER, identity_verified=True)
NOW = datetime(2026, 10, 31, 20, tzinfo=UTC)
ETA = ArrivalEstimate(
    8, NOW - timedelta(minutes=1), NOW + timedelta(minutes=2), "rough_distance"
)


def test_noaa_global_view_does_not_grant_operations_or_contacts():
    assert can_view_professional_case(NOAA, CASE)
    assert can_view_professional_case(
        NOAA, replace(CASE, state_code=None, state_verified=False)
    )
    assert not can_view_report(NOAA, replace(CASE, submitted=False))
    assert not can_contact_reporter(NOAA, CASE, "phone")
    assert not can_update_case(NOAA, CASE)
    assert not can_change_responsibility(NOAA, CASE)


def test_statewide_browsing_is_not_participation():
    observer = replace(COORD, organization_id="D")
    assert can_view_report(observer, CASE)
    assert case_matches_filter(observer, CASE, "all_allowed")
    assert not case_matches_filter(observer, CASE, "my_center")
    assert not can_contact_reporter(observer, CASE, "phone")
    assert not can_update_case(observer, CASE)


@pytest.mark.parametrize(
    "state,verified", [(None, False), ("CA", False), ("AK", True), ("XX", True)]
)
def test_unverified_or_out_of_scope_geography_denied(state, verified):
    case = replace(CASE, state_code=state, state_verified=verified)
    assert not can_view_professional_case(COORD, case)
    assert not case_matches_filter(COORD, case, "my_center")
    assert not can_contact_reporter(COORD, case, "phone")


def test_multiple_approved_states_and_reporter_ownership():
    alaska = replace(CASE, state_code="AK")
    assert can_view_professional_case(
        replace(COORD, allowed_states=frozenset({"CA", "AK"})), alaska
    )
    assert can_view_report(REPORTER, alaska)
    assert can_view_report(REPORTER, replace(CASE, submitted=False))
    assert not can_view_professional_case(REPORTER, CASE)
    assert not can_view_report(replace(REPORTER, user_id="stranger"), CASE)


@pytest.mark.parametrize(
    "change",
    [
        {"identity_verified": False},
        {"enabled": False},
        {"membership_verified": False},
        {"organization_id": None},
        {"role": "made-up"},
    ],
)
def test_unverified_disabled_or_revoked_identity_denied(change):
    actor = replace(COORD, **change)
    assert not can_view_professional_case(actor, CASE)
    assert not can_contact_reporter(actor, CASE, "phone")


@pytest.mark.parametrize(
    "org,scope", [("A", "leading"), ("B", "supporting"), ("C", "receiving")]
)
def test_my_center_includes_lead_accepted_support_and_confirmed_receiver(org, scope):
    actor = replace(COORD, organization_id=org)
    assert case_matches_filter(actor, CASE, "my_center")
    assert case_matches_filter(actor, CASE, scope)
    assert can_update_case(actor, CASE)
    assert can_change_responsibility(actor, CASE) == (org == "A")


def test_contact_channel_consent_and_closed_cases():
    assert can_contact_reporter(COORD, CASE, "phone")
    assert not can_contact_reporter(COORD, CASE, "text")
    assert not can_contact_reporter(COORD, CASE, "email")
    assert not can_contact_reporter(
        COORD, replace(CASE, reporter_contact_channels=frozenset()), "phone"
    )
    closed = replace(CASE, active=False)
    assert can_view_report(COORD, closed)
    assert not can_contact_reporter(COORD, closed, "phone")
    assert not can_update_case(COORD, closed)


def test_field_assignment_and_unapproved_volunteer_boundaries():
    assert can_view_professional_case(FIELD, CASE)
    assert case_matches_filter(FIELD, CASE, "assigned_to_me")
    assert can_contact_reporter(FIELD, CASE, "phone")
    for actor in [
        replace(FIELD, user_id="other"),
        replace(FIELD, organization_id="D"),
        replace(FIELD, role=Role.VOLUNTEER),
    ]:
        assert not can_view_professional_case(actor, CASE)
        assert not can_contact_reporter(actor, CASE, "phone")


def test_own_availability_does_not_cancel_report_or_grant_professional_access():
    assert can_update_own_availability(REPORTER, CASE)
    assert not can_update_own_availability(COORD, CASE)
    assert not can_update_own_availability(REPORTER, replace(CASE, active=False))
    assert not can_update_case(REPORTER, CASE)
    assert not case_matches_filter(REPORTER, CASE, "all_allowed")
    assert not case_matches_filter(COORD, CASE, "unknown-filter")


def test_reporter_contract_is_minimal_and_owner_scoped():
    result = reporter_update(REPORTER, CASE, ResponsePhase.EN_ROUTE, now=NOW, arrival=ETA)
    assert result["arrival_eta_minutes"] == 8
    assert result["eta_is_estimate"] is True
    assert result["eta_basis"] == "rough_distance"
    assert result["reporter_can_leave"] is True and result["leaving_cancels_report"] is False
    assert set(result) == {
        "case_id",
        "phase",
        "message",
        "arrival_eta_minutes",
        "eta_updated_at",
        "eta_basis",
        "eta_is_estimate",
        "reporter_can_leave",
        "leaving_cancels_report",
    }
    with pytest.raises(PermissionError):
        reporter_update(COORD, CASE, ResponsePhase.EN_ROUTE, now=NOW, arrival=ETA)


@pytest.mark.parametrize(
    "phase",
    [
        ResponsePhase.RECEIVED,
        ResponsePhase.ACCEPTED,
        ResponsePhase.ON_SCENE,
        ResponsePhase.ANIMAL_LOCATED,
        ResponsePhase.CLOSED,
    ],
)
def test_no_travel_eta_before_departure_or_after_arrival(phase):
    result = reporter_update(REPORTER, CASE, phase, now=NOW, arrival=ETA)
    assert result["arrival_eta_minutes"] is None
    assert result["eta_updated_at"] is None
    assert "located" not in result["message"] or phase == ResponsePhase.ANIMAL_LOCATED


@pytest.mark.parametrize(
    "estimate",
    [
        replace(ETA, valid_until=NOW - timedelta(seconds=1)),
        replace(ETA, updated_at=NOW + timedelta(seconds=1)),
        replace(ETA, minutes=-1),
        replace(ETA, minutes=float("nan")),
        replace(ETA, minutes=True),
        replace(ETA, basis="unknown"),
        replace(ETA, updated_at=NOW.replace(tzinfo=None)),
    ],
)
def test_invalid_stale_or_future_eta_is_unavailable(estimate):
    result = reporter_update(REPORTER, CASE, ResponsePhase.EN_ROUTE, now=NOW, arrival=estimate)
    assert result["arrival_eta_minutes"] is None and result["eta_is_estimate"] is False


def test_naive_server_time_and_unknown_phase_rejected():
    with pytest.raises(ValueError):
        reporter_update(REPORTER, CASE, ResponsePhase.EN_ROUTE, now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        reporter_update(REPORTER, CASE, "fake-status", now=NOW)


def test_remote_response_eta_can_exceed_one_day():
    result = reporter_update(
        REPORTER, CASE, ResponsePhase.EN_ROUTE, now=NOW, arrival=replace(ETA, minutes=2880)
    )
    assert result["arrival_eta_minutes"] == 2880
