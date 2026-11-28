from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.access.boundary import NetworkBoundaryMiddleware
from lifejacket.access.identity import IdentityUnavailable, InvalidIdentity, VerifiedIdentity
from lifejacket.api.routes import reporter_phone as routes
from lifejacket.config import settings
from lifejacket.models import repository
from lifejacket.models.db import get_session
from lifejacket.models.schemas import ConversationStage
from lifejacket.models.tables import (
    AccessMembershipRow,
    AccessUserRow,
    Base,
    IncidentRow,
    NetworkCaseRow,
    ReporterDraftRow,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reporter.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(routes.router)
    app.add_middleware(NetworkBoundaryMiddleware)
    monkeypatch.setattr(settings, "network_auth_enabled", True)
    monkeypatch.setattr(settings, "reporter_phone_enabled", True)
    monkeypatch.setattr(settings, "firebase_auth_project_id", "test-project")

    def sessions():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions

    def verify(token, project):
        assert project == "test-project"
        if token == "bad":
            raise InvalidIdentity("SECRET")
        if token == "down":
            raise IdentityUnavailable("SECRET")
        return VerifiedIdentity(
            "https://securetoken.google.com/test-project",
            token,
            phone_number="+12025550123" if token != "email-only" else None,
            sign_in_provider="password" if token == "email-only" else "phone",
            auth_time=int(datetime.now(UTC).timestamp()) - (3600 if token == "old" else 0),
        )

    monkeypatch.setattr(routes, "verify_provider_token", verify)

    @app.get("/incidents/{rest:path}")
    def legacy(rest: str):
        return {"secret": "NEVER"}

    with TestClient(app) as client:
        yield client, factory


def draft(client):
    r = client.post("/reporter/drafts")
    assert r.status_code == 200, r.text
    data = r.json()
    return data["turn"]["incident_id"], data["draft_key"]


def finish(factory, incident_id):
    with factory() as session:
        state = repository.load_conversation_state(session, incident_id)
        state.stage = ConversationStage.COMPLETE
        repository.save_conversation_state(session, incident_id, state)
        session.commit()


def submit(client, incident_id, key, token="owner", **extras):
    return client.post(
        f"/reporter/drafts/{incident_id}/submit",
        json={"draft_key": key, "id_token": token, "contact_channels": ["text"], **extras},
    )


def test_draft_is_private_expiring_and_not_a_submitted_case(api):
    client, factory = api
    incident_id, key = draft(client)
    with factory() as session:
        row = session.get(ReporterDraftRow, incident_id)
        assert key not in row.key_hash and len(row.key_hash) == 64
        assert row.submitted_at is None
        assert session.get(NetworkCaseRow, incident_id) is None
    path = f"/reporter/drafts/{incident_id}/turn"
    assert (
        client.post(path, json={"draft_key": "wrong-key-which-is-long-enough"}).status_code
        == 404
    )
    assert client.post(path, json={"draft_key": key}).status_code == 200
    assert client.get(f"/incidents/{incident_id}").status_code == 403
    with factory() as session:
        session.get(ReporterDraftRow, incident_id).expires_at = datetime.now() - timedelta(
            seconds=1
        )
        session.commit()
    assert client.post(path, json={"draft_key": key}).status_code == 404


@pytest.mark.parametrize(
    "token,code", [("bad", 401), ("down", 503), ("email-only", 403), ("old", 401)]
)
def test_verified_recent_phone_required_on_server(api, token, code):
    client, factory = api
    incident_id, key = draft(client)
    finish(factory, incident_id)
    r = submit(client, incident_id, key, token)
    assert r.status_code == code and "SECRET" not in r.text
    assert submit(client, incident_id, key, phone_verified=True).status_code == 422
    with factory() as session:
        assert session.get(NetworkCaseRow, incident_id) is None


def test_submission_requires_finished_draft_and_is_idempotent_owned_and_minimal(api):
    client, factory = api
    incident_id, key = draft(client)
    assert submit(client, incident_id, key).status_code == 409
    finish(factory, incident_id)
    assert submit(client, incident_id, key).status_code == 200
    assert submit(client, incident_id, key).status_code == 200
    assert submit(client, incident_id, key, "other").status_code == 404
    assert (
        client.post(
            f"/reporter/drafts/{incident_id}/turn", json={"draft_key": key}
        ).status_code
        == 404
    )
    with factory() as session:
        row = session.get(ReporterDraftRow, incident_id)
        assert row.contact_channels == ["text"] and row.phone_number == "+12025550123"
        access = session.get(NetworkCaseRow, incident_id)
        assert access.submitted and not access.verified_at and not access.state_code
        assert session.scalar(select(func.count()).select_from(AccessMembershipRow)) == 0
        assert session.get(IncidentRow, incident_id).reporter_phone is None
    path = f"/reporter/reports/{incident_id}/status"
    assert client.post(path, json={"id_token": "other"}).status_code == 404
    response = client.post(path, json={"id_token": "owner"})
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert set(response.json()) == {
        "case_id",
        "phase",
        "message",
        "arrival_eta_minutes",
        "eta_updated_at",
        "eta_basis",
        "eta_is_estimate",
        "reporter_can_leave",
        "leaving_cancels_report",
        "presence",
    }
    assert (
        response.json()["phase"] == "received"
        and response.json()["arrival_eta_minutes"] is None
    )
    assert client.post("/reporter/reports", json={"id_token": "other"}).json() == []
    assert (
        client.post("/reporter/reports", json={"id_token": "owner"}).json()[0]["case_id"]
        == incident_id
    )
    before = response.json()["phase"]
    assert (
        client.post(
            f"/reporter/reports/{incident_id}/presence",
            json={"id_token": "owner", "presence": "left"},
        ).json()["leaving_cancels_report"]
        is False
    )
    assert client.post(path, json={"id_token": "owner"}).json()["phase"] == before
    with factory() as session:
        access = session.get(NetworkCaseRow, incident_id)
        access.response_phase = "animal_located"
        session.commit()
    assert client.post(path, json={"id_token": "owner"}).json()["phase"] == "received"
    with factory() as session:
        access = session.get(NetworkCaseRow, incident_id)
        access.verified_at = datetime.now()
        access.verified_by = "reviewer"
        session.commit()
    assert client.post(path, json={"id_token": "owner"}).json()["phase"] == "animal_located"
    with factory() as session:
        session.get(AccessUserRow, access.reporter_user_id).enabled = False
        session.commit()
    assert client.post(path, json={"id_token": "owner"}).status_code == 403


def test_flags_fail_closed_and_legacy_paths_remain_blocked(api, monkeypatch):
    client, _ = api
    for path in [
        "/intake/start",
        "/incidents/x/photos/y",
        "/responders/incident/x/eta",
        "/network/cases",
    ]:
        assert client.post(path).status_code == 403
    monkeypatch.setattr(settings, "reporter_phone_enabled", False)
    assert client.post("/reporter/drafts").status_code == 403
    monkeypatch.setattr(settings, "network_auth_enabled", False)
    assert client.post("/reporter/drafts").status_code == 503


def test_managed_phone_claims_keep_revocation_checks(monkeypatch):
    from firebase_admin import auth
    from lifejacket.access import identity

    monkeypatch.setattr(identity, "_firebase_app", lambda project: "test-app")
    claims = {
        "iss": "https://securetoken.google.com/test-project",
        "aud": "test-project",
        "sub": "verified-subject",
        "phone_number": "+12025550123",
        "firebase": {"sign_in_provider": "phone"},
        "auth_time": 123,
    }

    def verified(token, *, app, check_revoked):
        assert token == "fictional" and app == "test-app" and check_revoked is True
        return claims

    monkeypatch.setattr(auth, "verify_id_token", verified)
    result = identity.verify_provider_token("fictional", "test-project")
    assert result.phone_number == "+12025550123" and result.sign_in_provider == "phone"
    assert result.auth_time == 123 and result.email_verified is False


def test_validation_response_never_echoes_credentials():
    import asyncio

    from fastapi.exceptions import RequestValidationError
    from lifejacket.api.main import private_reporter_validation
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "path": "/reporter/drafts",
            "method": "POST",
            "headers": [],
            "query_string": b"",
        }
    )
    error = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "field"),
                "input": {"id_token": "SECRET", "draft_key": "SECRET"},
            }
        ]
    )
    result = asyncio.run(private_reporter_validation(request, error))
    assert result.status_code == 422 and b"SECRET" not in result.body
