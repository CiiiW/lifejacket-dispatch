from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.access.boundary import NetworkBoundaryMiddleware
from lifejacket.access.dependencies import AccessSession, current_access_session
from lifejacket.access.identity import VerifiedIdentity
from lifejacket.access.memberships import ResolvedAccess
from lifejacket.access.policy import Principal, Role
from lifejacket.api.routes import network_actions, reporter_phone
from lifejacket.config import settings
from lifejacket.models.db import get_session
from lifejacket.models.tables import (
    AccessAuditRow,
    AccessUserRow,
    Base,
    IncidentRow,
    NetworkCaseAssigneeRow,
    NetworkCaseOrganizationRow,
    NetworkCaseRow,
    NetworkResponseEventRow,
    ReporterDraftRow,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


def actor(org="A", role=Role.CENTER_COORDINATOR, user="staff", states=("CA",)):
    return Principal(
        user,
        role,
        identity_verified=True,
        organization_id=org,
        membership_verified=True,
        allowed_states=frozenset(states),
    )


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'actions.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(network_actions.router)
    app.include_router(reporter_phone.router)
    app.add_middleware(NetworkBoundaryMiddleware)
    for name in [
        "network_auth_enabled",
        "network_case_actions_enabled",
        "reporter_phone_enabled",
    ]:
        monkeypatch.setattr(settings, name, True)
    monkeypatch.setattr(settings, "firebase_auth_project_id", "fixture")
    current = [actor()]

    def access():
        return AccessSession(
            VerifiedIdentity("fixture", "staff"), ResolvedAccess(current[0], ())
        )

    def sessions():
        with factory() as session:
            yield session

    app.dependency_overrides[current_access_session] = access
    app.dependency_overrides[get_session] = sessions
    monkeypatch.setattr(
        reporter_phone,
        "verify_provider_token",
        lambda token, project: VerifiedIdentity(
            "fixture",
            token,
            phone_number="+12025550123",
            sign_in_provider="phone",
            auth_time=int(datetime.now(UTC).timestamp()),
        ),
    )
    with factory() as session:
        session.add(
            AccessUserRow(user_id="owner", issuer="fixture", subject="owner", enabled=True)
        )
        session.add(
            IncidentRow(
                incident_id="case",
                status="awaiting_dispatch",
                report_json={"secret": "INTERNAL"},
                latitude=1,
                longitude=2,
            )
        )
        session.add(
            NetworkCaseRow(
                incident_id="case",
                reporter_user_id="owner",
                submitted=True,
                state_code="CA",
                verified_at=datetime.now(),
                verified_by="reviewer",
                lead_org_id="A",
                response_phase="received",
            )
        )
        session.add(
            NetworkCaseOrganizationRow(
                incident_id="case", organization_id="B", kind="supporting", accepted=True
            )
        )
        session.add(
            NetworkCaseAssigneeRow(
                incident_id="case", user_id="rescuer", organization_id="B", accepted=True
            )
        )
        session.add(
            ReporterDraftRow(
                incident_id="case",
                key_hash="x" * 64,
                expires_at=datetime.now() + timedelta(days=1),
                submitted_user_id="owner",
                submitted_at=datetime.now(),
                phone_number="+12025550123",
                contact_channels=["text"],
                presence="left",
            )
        )
        session.commit()
    with TestClient(app) as client:
        yield client, factory, current


def change(client, phase, revision, **extra):
    return client.patch(
        "/network/cases/case/response",
        json={"phase": phase, "revision": revision, "confirmed": True, **extra},
    )


def test_confirmed_lifecycle_reaches_only_own_reporter_minimal_status(api):
    client, factory, _ = api
    for revision, phase in enumerate(
        ["accepted", "en_route", "on_scene", "animal_located", "closed"]
    ):
        result = change(
            client,
            phase,
            revision,
            **({"closure_reason": "rescue_complete"} if phase == "closed" else {}),
        )
        assert result.status_code == 200, result.text
        assert result.json()["revision"] == revision + 1
        reporter = client.post("/reporter/reports/case/status", json={"id_token": "owner"})
        assert reporter.status_code == 200 and reporter.json()["phase"] == phase
        assert reporter.json()["arrival_eta_minutes"] is None
        assert (
            "phone_number" not in reporter.text
            and "INTERNAL" not in reporter.text
            and "latitude" not in reporter.text
        )
        assert (
            client.post(
                "/reporter/reports/case/status", json={"id_token": "unrelated"}
            ).status_code
            == 404
        )
    assert client.get("/network/cases/case/reporter-contact").status_code == 403
    assert change(client, "accepted", 5).status_code == 403
    with factory() as session:
        events = session.scalars(
            select(NetworkResponseEventRow).order_by(NetworkResponseEventRow.revision)
        ).all()
        assert [event.phase for event in events] == [
            "accepted",
            "en_route",
            "on_scene",
            "animal_located",
            "closed",
        ]
        assert all(
            event.actor_user_id == "staff" and event.organization_id == "A" for event in events
        )


def test_contact_is_case_scoped_text_only_audited_and_revocable(api):
    client, factory, current = api
    response = client.get("/network/cases/case/reporter-contact")
    assert response.status_code == 200 and response.json() == {
        "case_id": "case",
        "phone_number": "+12025550123",
        "channels": ["text"],
        "presence": "left",
    }
    assert "no-store" in response.headers["cache-control"]
    with factory() as session:
        events = session.scalars(select(AccessAuditRow)).all()
        assert len(events) == 1 and events[0].kind == "reporter_contact_viewed"
        assert "+12025550123" not in str(events[0].details)

    assert (
        client.post(
            "/reporter/reports/case/contact-preferences",
            json={"id_token": "unrelated", "contact_channels": []},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/reporter/reports/case/contact-preferences",
            json={"id_token": "owner", "contact_channels": []},
        ).status_code
        == 200
    )
    assert client.get("/network/cases/case/reporter-contact").status_code == 403
    current[0] = actor("B", Role.RESCUER, "rescuer")
    assert change(client, "accepted", 0).status_code == 200
    with factory() as session:
        session.get(NetworkCaseAssigneeRow, ("case", "rescuer", "B")).accepted = False
        session.commit()
    assert client.get("/network/cases/case/response").status_code == 404
    assert change(client, "en_route", 1).status_code == 404


@pytest.mark.parametrize(
    "person",
    [
        actor("N", Role.NOAA, states=()),
        actor("C"),
        actor("B", Role.RESCUER, "unassigned"),
        actor("B", Role.RESCUER, "rescuer", ("AK",)),
    ],
)
def test_state_browsing_and_noaa_do_not_imply_operational_contact(api, person):
    client, _, current = api
    current[0] = person
    r = client.get("/network/cases/case/response")
    if r.status_code == 200:
        assert r.json()["allowed_transitions"] == [] and r.json()["contact_channels"] == []
    else:
        assert r.status_code == 404
    assert client.get("/network/cases/case/reporter-contact").status_code in {403, 404}
    assert change(client, "accepted", 0).status_code in {403, 404}


def test_support_center_can_update_but_only_lead_coordinator_closes(api):
    client, factory, current = api
    current[0] = actor("B")
    assert client.get("/network/cases/case/response").json()["allowed_transitions"] == [
        "accepted"
    ]
    assert change(client, "accepted", 0).status_code == 200
    assert change(client, "closed", 1, closure_reason="transferred").status_code == 409
    with factory() as session:
        session.get(NetworkCaseOrganizationRow, ("case", "B", "supporting")).accepted = False
        session.commit()
    assert client.get("/network/cases/case/response").json()["contact_channels"] == []
    assert client.get("/network/cases/case/reporter-contact").status_code == 403
    assert change(client, "en_route", 1).status_code == 403


def test_revision_transition_and_human_confirmation_guards(api):
    client, factory, _ = api
    assert change(client, "en_route", 0).status_code == 409
    assert change(client, "closed", 0, closure_reason="rescue_complete").status_code == 409
    assert change(client, "closed", 0).status_code == 422
    assert change(client, "accepted", 0, confirmed=False).status_code == 422
    assert change(client, "accepted", 0, closure_reason="transferred").status_code == 422
    assert change(client, "accepted", 0).status_code == 200
    assert change(client, "en_route", 0).status_code == 409
    assert change(client, "en_route", 1).status_code == 200
    with factory() as session:
        assert len(session.scalars(select(NetworkResponseEventRow)).all()) == 2


def test_flags_and_unreviewed_scope_fail_closed(api, monkeypatch):
    client, factory, _ = api
    with factory() as session:
        session.get(NetworkCaseRow, "case").verified_at = None
        session.commit()
    assert client.get("/network/cases/case/response").status_code == 404
    monkeypatch.setattr(settings, "network_case_actions_enabled", False)
    assert client.get("/network/cases/case/response").status_code == 503
    assert change(client, "accepted", 0).status_code == 403
