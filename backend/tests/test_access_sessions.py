import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.access import dependencies
from lifejacket.access.identity import IdentityUnavailable, InvalidIdentity, VerifiedIdentity
from lifejacket.access.memberships import (
    AccessDenied,
    approve_membership,
    approve_organization,
    revoke_membership,
)
from lifejacket.api.routes.access import router
from lifejacket.config import settings
from lifejacket.models.db import get_session
from lifejacket.models.tables import (
    AccessAuditRow,
    AccessMembershipRow,
    AccessOrganizationRow,
    AccessUserRow,
    Base,
    IncidentRow,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

ISSUER = "https://securetoken.google.com/demo-identity"


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def sessions():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    monkeypatch.setattr(settings, "network_auth_enabled", True)
    monkeypatch.setattr(settings, "firebase_auth_project_id", "demo-identity")

    def verify(token, project):
        assert project == "demo-identity"
        if token == "bad-token":
            raise InvalidIdentity("provider internal diagnostics")
        if token == "unavailable":
            raise IdentityUnavailable("private project diagnostic")
        return VerifiedIdentity(ISSUER, token, "test@noaa.gov", token != "unverified")

    monkeypatch.setattr(dependencies, "verify_provider_token", verify)
    with TestClient(app) as client:
        yield client, factory


def me(client, token="subject-a", org=None, **extra):
    headers = {"Authorization": "Bearer " + token}
    if org is not None:
        headers["X-LifeJacket-Organization"] = org
    return client.get("/access/me", headers=headers | extra)


def grant(
    factory, user_id, kind="rescue_center", role="center_coordinator", states=None, org="A"
):
    states = ([] if kind == "noaa" else ["CA"]) if states is None else states
    with factory() as session:
        approve_organization(
            session, org, "Fictional test organization", kind, states, "test-admin"
        )
        member = approve_membership(session, user_id, org, role, states, "test-admin")
        return member.membership_id


def test_signin_is_personal_only_and_issuer_subject_identity_is_stable(api):
    client, factory = api
    first = me(client, **{"X-Role": "noaa", "X-State": "AK"})
    assert first.status_code == 200
    body = first.json()
    assert body["role"] == "reporter" and body["organizations"] == []
    assert body["selected_organization_id"] is None and body["authorized_states"] == []
    assert me(client).json()["account_id"] == body["account_id"]
    # Same email/domain does not merge provider subjects or grant NOAA membership.
    assert me(client, "subject-b").json()["account_id"] != body["account_id"]
    assert first.headers["cache-control"] == "private, no-store"
    assert "subject-a" not in first.text
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AccessUserRow)) == 2
        assert session.scalar(select(func.count()).select_from(AccessMembershipRow)) == 0


def test_approved_membership_is_server_selected_and_persists(api):
    client, factory = api
    uid = me(client).json()["account_id"]
    grant(factory, uid)
    personal = me(client).json()
    assert personal["role"] == "reporter"
    assert personal["organizations"][0]["role"] == "center_coordinator"
    selected = me(client, org="A", **{"X-Role": "noaa", "X-State": "AK"}).json()
    assert selected["role"] == "center_coordinator" and selected["authorized_states"] == ["CA"]
    assert selected["selected_organization_id"] == "A"
    assert me(client, "other-person", "A").status_code == 403
    assert me(client, org="does-not-exist").status_code == 403
    with factory() as session:
        assert set(session.scalars(select(AccessAuditRow.kind))) >= {
            "personal_account_created",
            "organization_approved",
            "membership_approved",
        }


def test_noaa_needs_noaa_org_and_explicit_verified_membership(api):
    client, factory = api
    uid = me(client).json()["account_id"]
    grant(factory, uid, kind="noaa", role="noaa", org="NOAA")
    body = me(client, org="NOAA").json()
    assert body["role"] == "noaa" and body["authorized_states"] == []


def test_revocation_and_disabling_take_effect_with_the_same_token(api):
    client, factory = api
    uid = me(client).json()["account_id"]
    member_id = grant(factory, uid)
    assert me(client, org="A").status_code == 200
    with factory() as session:
        revoke_membership(session, member_id, "test-admin")
        revoke_membership(session, member_id, "test-admin")
        assert (
            len(
                list(
                    session.scalars(
                        select(AccessAuditRow).where(
                            AccessAuditRow.kind == "membership_revoked"
                        )
                    )
                )
            )
            == 1
        )
    assert me(client, org="A").status_code == 403
    assert me(client).json()["organizations"] == []
    with factory() as session:
        session.get(AccessUserRow, uid).enabled = False
        session.commit()
    assert me(client).status_code == 403


@pytest.mark.parametrize(
    "change", ["pending", "org-disabled", "org-unverified", "bad-state", "bad-role"]
)
def test_unapproved_or_corrupt_professional_contexts_fail_closed(api, change):
    client, factory = api
    uid = me(client).json()["account_id"]
    member_id = grant(factory, uid)
    with factory() as session:
        member, org = (
            session.get(AccessMembershipRow, member_id),
            session.get(AccessOrganizationRow, "A"),
        )
        if change == "pending":
            member.status = "pending"
        elif change == "org-disabled":
            org.enabled = False
        elif change == "org-unverified":
            org.verified_at = None
        elif change == "bad-state":
            member.approved_states = ["AK"]
        else:
            member.role = "noaa"
        session.commit()
    assert me(client, org="A").status_code == 403
    assert me(client).json()["organizations"] == []


def test_unverified_email_cannot_enter_professional_context(api):
    client, factory = api
    uid = me(client, "unverified").json()["account_id"]
    grant(factory, uid)
    assert me(client, "unverified").json()["organizations"] == []
    assert me(client, "unverified", "A").status_code == 403


def test_missing_bad_or_unavailable_token_does_not_create_account(api):
    client, factory = api
    assert client.get("/access/me").status_code == 401
    assert client.get("/access/me", headers={"Authorization": "Basic abc"}).status_code == 401
    assert me(client, "bad-token").status_code == 401
    assert me(client, "unavailable").status_code == 503
    assert "diagnostic" not in me(client, "unavailable").text
    assert "diagnostic" not in me(client, "bad-token").text
    assert me(client, "x" * 8193).status_code == 401
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AccessUserRow)) == 0


def test_unconfigured_signin_fails_closed_and_keeps_existing_cases(api, monkeypatch):
    client, factory = api
    with factory() as session:
        session.add(IncidentRow(incident_id="existing", status="awaiting_dispatch"))
        session.commit()
    monkeypatch.setattr(settings, "network_auth_enabled", False)
    assert me(client).status_code == 503
    monkeypatch.setattr(settings, "network_auth_enabled", True)
    monkeypatch.setattr(settings, "firebase_auth_project_id", None)
    assert me(client).status_code == 503
    with factory() as session:
        assert session.get(IncidentRow, "existing").status == "awaiting_dispatch"
        assert session.scalar(select(func.count()).select_from(AccessUserRow)) == 0


@pytest.mark.parametrize(
    "kind,role,states",
    [
        ("rescue_center", "noaa", ["CA"]),
        ("noaa", "rescuer", []),
        ("rescue_center", "rescuer", ["XX"]),
        ("rescue_center", "rescuer", []),
        ("rescue_center", "reporter", ["CA"]),
    ],
)
def test_invalid_admin_grants_do_not_survive(api, kind, role, states):
    client, factory = api
    uid = me(client).json()["account_id"]
    with factory() as session:
        approve_organization(
            session, "A", "Fictional", kind, [] if kind == "noaa" else ["CA"], "test-admin"
        )
        with pytest.raises((ValueError, AccessDenied)):
            approve_membership(session, uid, "A", role, states, "test-admin")
        session.rollback()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AccessMembershipRow)) == 0


def test_access_table_init_is_additive_and_repeatable(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    IncidentRow.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            IncidentRow.__table__.insert().values(incident_id="preserved", status="closed")
        )
    spec = importlib.util.spec_from_file_location(
        "access_admin", Path(__file__).resolve().parents[2] / "scripts/network_access_admin.py"
    )
    admin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(admin)
    monkeypatch.setattr(admin, "engine", engine)
    monkeypatch.setattr("sys.argv", ["network_access_admin.py", "init"])
    admin.main()
    admin.main()
    with sessionmaker(bind=engine)() as session:
        assert session.get(IncidentRow, "preserved").status == "closed"
        assert session.scalar(select(func.count()).select_from(AccessUserRow)) == 0
        assert session.scalar(select(func.count()).select_from(AccessMembershipRow)) == 0
