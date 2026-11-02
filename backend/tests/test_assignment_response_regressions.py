import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.api.routes.responders import router
from lifejacket.models.db import get_session
from lifejacket.models.tables import AssignmentRow, Base, IncidentRow, ResponderRow
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def api(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'assignments.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        session.add(IncidentRow(incident_id="case", status="awaiting_dispatch"))
        for org in ("A", "B", "C"):
            session.add(
                ResponderRow(
                    responder_id=org, name=f"Fictional team {org}", kind="organisation"
                )
            )
        session.commit()
    app = FastAPI()
    app.include_router(router)

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    with TestClient(app) as client:
        yield client, sessions


def offer(client, org):
    result = client.post(
        "/responders/assign",
        json={
            "incident_id": "case",
            "responder_id": org,
            "approved_by": "Fictional coordinator",
        },
    )
    assert result.status_code == 200
    return result.json()["assignment_id"]


def respond(client, id, accept):
    return client.post(f"/responders/assignments/{id}/respond", json={"accept": accept})


def snapshot(sessions):
    with sessions() as session:
        row = session.get(IncidentRow, "case")
        return row.status, row.assigned_responder_id


def test_another_team_declining_does_not_remove_active_primary(api):
    client, sessions = api
    a = offer(client, "A")
    assert respond(client, a, True).status_code == 200
    b = offer(client, "B")
    assert snapshot(sessions) == ("accepted", "A")
    assert respond(client, b, False).status_code == 200
    assert snapshot(sessions) == ("accepted", "A")


@pytest.mark.parametrize("phase", ["en_route", "on_scene"])
def test_additional_offers_acceptances_and_retries_preserve_primary_progress(api, phase):
    client, sessions = api
    a = offer(client, "A")
    respond(client, a, True)
    with sessions() as session:
        session.get(IncidentRow, "case").status = phase
        session.commit()
    b = offer(client, "B")
    assert snapshot(sessions) == (phase, "A")
    assert respond(client, b, True).status_code == 200
    assert snapshot(sessions) == (phase, "A")
    assert respond(client, b, True).status_code == 200
    assert snapshot(sessions) == (phase, "A")
    assert respond(client, a, False).status_code == 409
    assert snapshot(sessions) == (phase, "A")


def test_declining_one_pending_offer_retains_other_pending_offer(api):
    client, sessions = api
    a, b = offer(client, "A"), offer(client, "B")
    respond(client, a, False)
    assert snapshot(sessions) == ("dispatched", None)
    assert respond(client, a, False).status_code == 200
    assert respond(client, a, True).status_code == 409
    respond(client, b, False)
    assert snapshot(sessions) == ("awaiting_dispatch", None)


@pytest.mark.parametrize("phase", ["resolved", "cancelled", "guidance_only"])
def test_closed_case_cannot_be_reopened_by_offer_or_response(api, phase):
    client, sessions = api
    a = offer(client, "A")
    with sessions() as session:
        session.get(IncidentRow, "case").status = phase
        session.commit()
    assert (
        client.post(
            "/responders/assign",
            json={
                "incident_id": "case",
                "responder_id": "B",
                "approved_by": "Fictional coordinator",
            },
        ).status_code
        == 409
    )
    assert respond(client, a, True).status_code == 409
    assert snapshot(sessions) == (phase, None)
    with sessions() as session:
        assert session.get(AssignmentRow, a).status == "offered"
        assert len(list(session.scalars(select(AssignmentRow)))) == 1
