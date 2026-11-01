from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.access.boundary import NetworkBoundaryMiddleware
from lifejacket.access.dependencies import AccessSession, current_access_session
from lifejacket.access.identity import VerifiedIdentity
from lifejacket.access.memberships import ResolvedAccess
from lifejacket.access.policy import Principal, Role
from lifejacket.api.routes.network import router
from lifejacket.config import settings
from lifejacket.models.db import get_session
from lifejacket.models.tables import (
    Base,
    IncidentRow,
    NetworkCaseAssigneeRow,
    NetworkCaseOrganizationRow,
    NetworkCaseRow,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def network(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'network.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(NetworkBoundaryMiddleware)
    monkeypatch.setattr(settings, "network_auth_enabled", True)
    monkeypatch.setattr(settings, "firebase_auth_project_id", None)
    current = [
        Principal(
            "person",
            Role.CENTER_COORDINATOR,
            identity_verified=True,
            organization_id="A",
            membership_verified=True,
            allowed_states=frozenset({"CA"}),
        )
    ]

    def access():
        return AccessSession(VerifiedIdentity("test", "test"), ResolvedAccess(current[0], ()))

    def sessions():
        with factory() as session:
            yield session

    app.dependency_overrides[current_access_session] = access
    app.dependency_overrides[get_session] = sessions

    @app.api_route("/incidents/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    def legacy(rest: str):
        return {"secret": "must never leak"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    with factory() as session:
        for name, state, submitted, verified in [
            ("ca", "CA", True, True),
            ("ak", "AK", True, True),
            ("draft", "CA", False, True),
            ("unknown", None, True, False),
            ("unverified", "CA", True, False),
        ]:
            session.add(
                IncidentRow(
                    incident_id=name,
                    status="en_route",
                    reporter_id="person",
                    reporter_phone="SECRET PHONE",
                    report_json={"secret": "SECRET REPORT"},
                    metrics_json={"duplicate_match": {"incident_id": "SECRET RELATED"}},
                    latitude=1,
                    longitude=2,
                )
            )
            session.add(
                NetworkCaseRow(
                    incident_id=name,
                    reporter_user_id="owner",
                    submitted=submitted,
                    state_code=state,
                    verified_at=datetime.now() if verified else None,
                    verified_by="reviewer" if verified else None,
                    lead_org_id="B",
                    response_phase="en_route",
                )
            )
        session.add(
            IncidentRow(
                incident_id="legacy", status="accepted", reporter_id="person", place_name="CA"
            )
        )
        session.commit()
    with TestClient(app) as client:
        yield client, factory, current, app


def ids(client, query=""):
    r = client.get("/network/cases" + query)
    assert r.status_code == 200
    return [row["incident_id"] for row in r.json()]


def test_center_state_scope_and_minimal_projection(network):
    client, _, _, _ = network
    assert ids(client) == ["ca"]
    response = client.get("/network/cases/ca")
    assert response.status_code == 200
    assert set(response.json()) == {
        "incident_id",
        "status",
        "state_code",
        "latitude",
        "longitude",
        "animal_group",
        "species_common_name",
        "severity_level",
        "lead_organization_id",
        "created_at",
    }
    assert "SECRET" not in response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("case", ["ak", "draft", "unknown", "unverified", "legacy", "missing"])
def test_detail_does_not_bypass_list_scope(network, case):
    assert network[0].get("/network/cases/" + case).status_code == 404


def test_noaa_reads_submitted_across_states_but_no_drafts_or_legacy(network):
    client, _, current, _ = network
    current[0] = Principal(
        "person",
        Role.NOAA,
        identity_verified=True,
        organization_id="NOAA",
        membership_verified=True,
    )
    assert set(ids(client)) == {"ca", "ak", "unknown", "unverified"}


@pytest.mark.parametrize(
    "role,verified,member",
    [
        (Role.REPORTER, True, False),
        (Role.VOLUNTEER, True, False),
        (Role.NOAA, False, True),
        (Role.CENTER_COORDINATOR, True, False),
    ],
)
def test_unapproved_roles_cannot_read_professional_cases(network, role, verified, member):
    client, _, current, _ = network
    current[0] = Principal(
        "person",
        role,
        identity_verified=verified,
        organization_id="A",
        membership_verified=member,
        allowed_states=frozenset({"CA"}),
    )
    assert ids(client) == []
    assert client.get("/network/cases/ca").status_code == 404


def test_filters_only_narrow_scope_and_accepted_relationships(network):
    client, factory, _, _ = network
    assert ids(client, "?scope=my_center") == []
    with factory() as session:
        session.add(
            NetworkCaseOrganizationRow(
                incident_id="ca", organization_id="A", kind="supporting", accepted=False
            )
        )
        session.add(
            NetworkCaseOrganizationRow(
                incident_id="ak", organization_id="A", kind="supporting", accepted=True
            )
        )
        session.commit()
    assert ids(client, "?scope=supporting") == []
    with factory() as session:
        session.get(NetworkCaseOrganizationRow, ("ca", "A", "supporting")).accepted = True
        session.commit()
    assert ids(client, "?scope=my_center") == ["ca"]
    assert ids(client, "?scope=supporting") == ["ca"]
    assert ids(client, "?scope=leading") == []
    assert ids(client, "?scope=receiving") == []
    assert ids(client, "?scope=assigned_to_me") == []
    assert client.get("/network/cases?scope=anything").status_code == 422


def test_rescuer_needs_accepted_person_and_org_in_selected_context(network):
    client, factory, current, _ = network
    current[0] = Principal(
        "person",
        Role.RESCUER,
        identity_verified=True,
        organization_id="A",
        membership_verified=True,
        allowed_states=frozenset({"CA"}),
    )
    with factory() as session:
        session.add(
            NetworkCaseAssigneeRow(
                incident_id="ca", user_id="person", organization_id="A", accepted=True
            )
        )
        session.commit()
    assert ids(client) == []
    with factory() as session:
        session.add(
            NetworkCaseOrganizationRow(
                incident_id="ca", organization_id="A", kind="supporting", accepted=True
            )
        )
        session.commit()
    assert ids(client) == ["ca"]
    with factory() as session:
        session.get(NetworkCaseAssigneeRow, ("ca", "person", "A")).accepted = False
        session.commit()
    assert ids(client) == []


def test_pagination_is_applied_after_authorization(network):
    client, _, _, _ = network
    assert ids(client, "?limit=1&offset=0") == ["ca"]
    assert ids(client, "?limit=1&offset=1") == []
    assert client.get("/network/cases?limit=101").status_code == 422


def test_reporter_only_gets_own_minimal_update_not_staff_location(network):
    client, _, current, _ = network
    assert client.get("/network/reports/ca").status_code == 404
    current[0] = Principal("owner", Role.REPORTER, identity_verified=True)
    r = client.get("/network/reports/ca")
    assert r.status_code == 200
    assert r.json()["phase"] == "en_route" and r.json()["arrival_eta_minutes"] is None
    assert r.json()["reporter_can_leave"] and not r.json()["leaving_cancels_report"]
    assert set(r.json()) == {
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
    assert client.get("/network/cases/ca").status_code == 404
    assert client.get("/network/reports/draft").status_code == 404
    current[0] = Principal("person", Role.REPORTER, identity_verified=True)
    assert client.get("/network/reports/legacy").status_code == 404


@pytest.mark.parametrize(
    "path,method",
    [
        ("/incidents/ca", "GET"),
        ("/incidents/ca/photos/p", "GET"),
        ("/incidents/ca/status", "PATCH"),
        ("/incidents/ca/log", "POST"),
        ("/responders/incident/ca/eta", "GET"),
        ("/coordination/ca", "POST"),
        ("/intake", "POST"),
        ("/openapi.json", "GET"),
        ("/drone-demo/frames", "GET"),
    ],
)
def test_network_mode_blocks_all_legacy_surfaces(network, path, method):
    response = network[0].request(method, path)
    assert response.status_code == 403 and "secret" not in response.text


def test_legacy_private_mode_compatibility_and_auth_required_on_new_routes(
    network, monkeypatch
):
    client, _, _, app = network
    assert client.get("/health").status_code == 200
    app.dependency_overrides.pop(current_access_session)
    assert client.get("/network/cases").status_code == 503  # No project configured in fixture.
    monkeypatch.setattr(settings, "network_auth_enabled", False)
    assert client.get("/incidents/ca").json() == {"secret": "must never leak"}
    assert client.get("/network/cases").status_code == 503


def test_real_session_dependency_revocation_and_claim_spoofing(network, monkeypatch):
    from lifejacket.access import dependencies
    from lifejacket.access.memberships import (
        approve_membership,
        approve_organization,
        ensure_account,
        revoke_membership,
    )

    client, factory, _, app = network
    app.dependency_overrides.pop(current_access_session)
    monkeypatch.setattr(settings, "firebase_auth_project_id", "fixture-project")
    identity = VerifiedIdentity(
        "https://securetoken.google.com/fixture-project",
        "signed-person",
        "person@example.org",
        True,
    )
    monkeypatch.setattr(dependencies, "verify_provider_token", lambda token, project: identity)
    assert client.get("/network/cases").status_code == 401
    headers = {"Authorization": "Bearer fixture-token", "X-Role": "noaa", "X-State": "AK"}
    assert client.get("/network/cases", headers=headers).json() == []
    with factory() as session:
        user = ensure_account(session, identity)
        approve_organization(
            session, "A", "Fictional center", "rescue_center", ["CA"], "reviewer"
        )
        member = approve_membership(
            session, user.user_id, "A", "center_coordinator", ["CA"], "reviewer"
        )
        member_id = member.membership_id
    headers["X-LifeJacket-Organization"] = "A"
    assert [
        r["incident_id"] for r in client.get("/network/cases", headers=headers).json()
    ] == ["ca"]
    assert client.get("/network/cases/ak", headers=headers).status_code == 404
    with factory() as session:
        revoke_membership(session, member_id, "reviewer")
    assert client.get("/network/cases/ca", headers=headers).status_code == 403
    assert client.get("/incidents/ca", headers=headers).status_code == 403


def test_case_admin_requires_reviewed_binding_and_records_audit(network):
    import importlib.util
    from pathlib import Path

    from lifejacket.models.tables import AccessAuditRow, AccessUserRow
    from sqlalchemy import select

    spec = importlib.util.spec_from_file_location(
        "case_admin", Path(__file__).resolve().parents[2] / "scripts/network_case_admin.py"
    )
    admin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(admin)
    client, factory, _, _ = network
    with factory() as session:
        with pytest.raises(ValueError):
            admin.review_case(session, "legacy", "XX", None, None, "reviewer")
        with pytest.raises(ValueError):
            admin.review_case(session, "legacy", "CA", "missing", None, "reviewer")
        with pytest.raises(ValueError):
            admin.review_case(session, "legacy", "CA", None, "missing", "reviewer")
        session.add(
            AccessUserRow(
                user_id="bound-owner", issuer="fixture", subject="bound", enabled=True
            )
        )
        session.commit()
        admin.review_case(session, "legacy", "CA", "bound-owner", None, "reviewer")
        with pytest.raises(ValueError):
            admin.review_case(session, "legacy", "CA", "other", None, "reviewer")
        assert (
            len(
                list(
                    session.scalars(
                        select(AccessAuditRow).where(
                            AccessAuditRow.kind == "network_case_reviewed"
                        )
                    )
                )
            )
            == 1
        )
        assert session.get(IncidentRow, "legacy").reporter_id == "person"
    assert "legacy" in ids(client)


def test_reporter_unreviewed_ownership_is_denied(network):
    client, _, current, _ = network
    current[0] = Principal("owner", Role.REPORTER, identity_verified=True)
    assert client.get("/network/reports/unverified").status_code == 404


def test_actual_app_boundary_blocks_every_registered_legacy_route(monkeypatch):
    from lifejacket.api.main import app

    monkeypatch.setattr(settings, "network_auth_enabled", True)
    client = TestClient(app)  # No lifespan: never initialize the configured application DB.
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        if path == "/health" or path == "/access/me" or path.startswith("/network/"):
            continue
        for method in operations.keys() & {"get", "post", "patch", "put", "delete"}:
            response = client.request(method.upper(), path)
            assert response.status_code == 403, (method, path, response.text)
            checked += 1
    assert checked > 20
