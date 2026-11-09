"""Monitoring chain and authorization regressions through real HTTP routes."""

# ruff: noqa: F811
from datetime import UTC, datetime, timedelta

import pytest
from lifejacket.access.policy import Role
from lifejacket.api.routes import drone_requests
from lifejacket.models.tables import CaseDroneRequestRow, IncidentRow, NetworkCaseRow
from sqlalchemy import select
from test_drone_requests import (
    BASE,
    change,
    drone_api,  # noqa: F401
    payload,
    upload,
)
from test_network_actions import actor, api  # noqa: F401


@pytest.fixture
def monitoring_api(drone_api):
    client, factory, current = drone_api
    client.app.include_router(drone_requests.monitoring_router)
    return client, factory, current


def future():
    return (datetime.now(UTC) + timedelta(hours=48)).isoformat()


def monitored(client):
    body = payload()
    body.update(purpose="monitoring", next_review_at=future())
    r = client.post(BASE, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def decide(client, row, action="continue", **extra):
    body = dict(
        revision=row["revision"],
        confirmed=True,
        action=action,
        reason="Coordinator reviewed the observation",
    )
    if action == "continue":
        body["next_review_at"] = future()
    body.update(extra)
    return client.post(BASE + "/" + row["request_id"] + "/monitoring", json=body)


def terminal(client, row):
    r = change(client, row, "approved", operator="Synthetic operator")
    assert r.status_code == 200, r.text
    r = change(client, r.json(), "in_progress")
    assert r.status_code == 200, r.text
    row = r.json()
    r = upload(client, row)
    assert r.status_code == 201, r.text
    row["revision"] = r.json()["revision"]
    r = change(client, row, "evidence_ready")
    assert r.status_code == 200, r.text
    r = change(client, r.json(), "reviewed", outcome="still_uncertain")
    assert r.status_code == 200, r.text
    return r.json()


def test_chain_requires_approval_and_rejects_repeat(monitoring_api):
    client, factory, _ = monitoring_api
    row = monitored(client)
    assert decide(client, row).status_code == 409
    row = terminal(client, row)
    r = decide(client, row)
    assert r.status_code == 200, r.text
    child_id = r.json()["monitoring_decision"]["next_request_id"]
    child = client.get(BASE + "/" + child_id).json()
    assert child["status"] == "requested" and child["revision"] == 0
    assert child["previous_request_id"] == row["request_id"]
    assert child["monitoring_root_request_id"] == row["request_id"]
    assert child["execution_kind"] == "recorded_demo"
    assert decide(client, row).status_code == 409
    queue = client.get("/network/monitoring").json()
    assert [x["request_id"] for x in queue["items"]] == [child_id]
    with factory() as session:
        assert len(session.scalars(select(CaseDroneRequestRow)).all()) == 2
        assert session.get(NetworkCaseRow, "case").response_phase == "received"
        assert session.get(IncidentRow, "case").report_json == {"secret": "INTERNAL"}


@pytest.mark.parametrize("action", ["finish", "escalate"])
def test_decisions_leave_case_open_and_remove_leaf(monitoring_api, action):
    client, factory, _ = monitoring_api
    row = monitored(client)
    row = change(client, row, "declined").json()
    r = decide(client, row, action)
    assert r.status_code == 200, r.text
    assert client.get("/network/monitoring").json()["total"] == 0
    with factory() as session:
        assert session.get(NetworkCaseRow, "case").response_phase == "received"


@pytest.mark.parametrize(
    "person,readable",
    [
        (actor("B"), True),
        (actor("B", Role.RESCUER, "rescuer"), True),
        (actor("C"), False),
        (actor("N", Role.NOAA, states=()), False),
        (actor("A", Role.REPORTER), False),
        (actor("A", states=("AK",)), False),
    ],
)
def test_queue_scope_and_write_permission(monitoring_api, person, readable):
    client, _, current = monitoring_api
    row = change(client, monitored(client), "declined").json()
    current[0] = person
    response = client.get("/network/monitoring")
    if readable:
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["can_decide"] is False
    else:
        assert response.status_code == 403 or response.json()["total"] == 0
    assert decide(client, row, "finish").status_code in {403, 404}


def test_stale_and_invalid_time_are_atomic(monitoring_api):
    client, factory, _ = monitoring_api
    row = change(client, monitored(client), "declined").json()
    assert decide(client, row, revision=99).status_code == 409
    assert decide(client, row, next_review_at="2020-01-01T00:00:00Z").status_code == 422
    assert decide(client, row, "finish", next_review_at=future()).status_code == 422
    with factory() as session:
        assert len(session.scalars(select(CaseDroneRequestRow)).all()) == 1
        assert session.get(CaseDroneRequestRow, row["request_id"]).revision == row["revision"]


def test_due_queue_and_closed_case(monitoring_api):
    client, factory, _ = monitoring_api
    row = monitored(client)
    with factory() as session:
        stored = session.get(CaseDroneRequestRow, row["request_id"])
        stored.payload_json = {**stored.payload_json, "next_review_at": "2020-01-01T00:00:00Z"}
        session.commit()
    response = client.get("/network/monitoring")
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["queue_status"] == "overdue"
    assert "no-store" in response.headers["cache-control"]
    with factory() as session:
        scope = session.get(NetworkCaseRow, "case")
        scope.response_phase = "closed"
        session.commit()
    assert client.get("/network/monitoring").json()["total"] == 0


def test_child_creation_failure_rolls_back_parent(monitoring_api, monkeypatch):
    from fastapi import HTTPException
    from lifejacket.services import drone_requests as service

    client, factory, _ = monitoring_api
    row = change(client, monitored(client), "declined").json()

    def fail(*args, **kwargs):
        raise HTTPException(409, "Synthetic child creation failure")

    monkeypatch.setattr(service, "create", fail)
    assert decide(client, row).status_code == 409
    with factory() as session:
        stored = session.get(CaseDroneRequestRow, row["request_id"])
        assert stored.revision == row["revision"]
        assert "monitoring_decision" not in stored.payload_json


@pytest.mark.parametrize(
    "hours,status,expected",
    [
        (0, "requested", "overdue"),
        (24, "requested", "due_soon"),
        (25, "requested", "scheduled"),
        (48, "reviewed", "needs_decision"),
    ],
)
def test_due_time_boundaries(hours, status, expected):
    from lifejacket.services.drone_requests import monitoring_item

    clock = datetime(2026, 11, 7, tzinfo=UTC)
    row = CaseDroneRequestRow(
        request_id="a" * 32,
        incident_id="case",
        status=status,
        payload_json={
            "purpose": "monitoring",
            "execution_kind": "recorded_demo",
            "objective": "Check activity",
            "next_review_at": (clock + timedelta(hours=hours)).isoformat(),
        },
    )
    assert monitoring_item(row, clock)["queue_status"] == expected


def test_verification_review_can_enter_monitoring(monitoring_api):
    client, _, _ = monitoring_api
    r = client.post(BASE, json=payload(next_review_at=future()))
    row = change(client, r.json(), "declined").json()
    assert client.get("/network/monitoring").json()["total"] == 1
    assert decide(client, row, "finish").status_code == 200


def test_queue_normalizes_offsets_for_chronological_sorting():
    from lifejacket.services.drone_requests import monitoring_item

    row = CaseDroneRequestRow(
        request_id="a" * 32,
        incident_id="case",
        status="requested",
        payload_json={
            "purpose": "monitoring",
            "execution_kind": "recorded_demo",
            "objective": "Check activity",
            "next_review_at": "2026-11-09T12:00:00-06:00",
        },
    )
    value = monitoring_item(row, datetime(2026, 11, 7, tzinfo=UTC))
    assert value["next_review_at"] == "2026-11-09T18:00:00+00:00"
