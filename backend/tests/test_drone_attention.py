"""Real API checks for durable attention and case-confined comparison."""
# ruff: noqa: F811

import pytest
from lifejacket.access.policy import Role
from lifejacket.models.tables import (
    CaseDroneEventRow,
    CaseDroneRequestRow,
    IncidentRow,
    NetworkCaseRow,
)
from sqlalchemy import select
from test_drone_requests import BASE, change, drone_api  # noqa: F401
from test_monitoring import decide, monitored, monitoring_api  # noqa: F401
from test_network_actions import actor, api  # noqa: F401

ATTENTION = "/network/monitoring/attention"


def escalated(client):
    row = change(client, monitored(client), "declined").json()
    response = decide(client, row, "escalate")
    assert response.status_code == 200, response.text
    return response.json()


def acknowledge(client, item, **extra):
    return client.post(
        BASE + "/" + item["request_id"] + "/attention",
        json={
            "revision": item["revision"],
            "kind": item["kind"],
            "attention_key": item["attention_key"],
            "confirmed": True,
            "note": "Coordinator is arranging the next review",
            **extra,
        },
    )


def overdue(factory, row, due="2020-01-01T00:00:00Z"):
    with factory() as session:
        stored = session.get(CaseDroneRequestRow, row["request_id"])
        stored.payload_json = {**stored.payload_json, "next_review_at": due}
        session.commit()


def test_escalation_persists_until_audited_acknowledgment(monitoring_api):
    client, factory, _ = monitoring_api
    row = escalated(client)
    assert client.get("/network/monitoring").json()["total"] == 0
    first = client.get(ATTENTION)
    assert first.status_code == 200 and "no-store" in first.headers["cache-control"]
    item = first.json()["items"][0]
    assert item["kind"] == "escalation"
    assert client.get(ATTENTION).json()["items"][0]["attention_key"] == item["attention_key"]
    assert acknowledge(client, item, revision=item["revision"] - 1).status_code == 409
    assert client.get(ATTENTION).json()["total"] == 1
    assert acknowledge(client, item).status_code == 200
    detail = client.get(BASE + "/" + item["request_id"]).json()
    assert detail["events"][-1]["kind"] == "attention_acknowledged"
    assert detail["events"][-1]["attention_kind"] == item["kind"]
    assert client.get(ATTENTION).json()["total"] == 0
    assert acknowledge(client, item).status_code == 409
    with factory() as session:
        assert session.get(NetworkCaseRow, "case").response_phase == "received"
        assert session.get(IncidentRow, "case").report_json == {"secret": "INTERNAL"}
        events = session.scalars(
            select(CaseDroneEventRow).where(CaseDroneEventRow.request_id == row["request_id"])
        ).all()
        event = next(e for e in events if e.kind == "attention_acknowledged")
        assert event.details_json["note"] == "Coordinator is arranging the next review"


def test_overdue_reminder_ack_is_schedule_specific(monitoring_api):
    client, factory, _ = monitoring_api
    row = monitored(client)
    overdue(factory, row)
    item = client.get(ATTENTION).json()["items"][0]
    assert item["kind"] == "overdue"
    assert acknowledge(client, item).status_code == 200
    assert client.get(ATTENTION).json()["total"] == 0
    assert client.get("/network/monitoring").json()["items"][0]["queue_status"] == "overdue"
    overdue(factory, row, "2020-01-02T00:00:00Z")
    new = client.get(ATTENTION).json()["items"][0]
    assert new["attention_key"] != item["attention_key"]


@pytest.mark.parametrize(
    "person,readable",
    [
        (actor("B"), True),
        (actor("B", Role.RESCUER, "rescuer"), True),
        (actor("C"), False),
        (actor("N", Role.NOAA, states=()), False),
        (actor("A", Role.REPORTER), False),
    ],
)
def test_attention_permissions(monitoring_api, person, readable):
    client, _, current = monitoring_api
    escalated(client)
    item = client.get(ATTENTION).json()["items"][0]
    current[0] = person
    response = client.get(ATTENTION)
    if readable:
        assert response.status_code == 200
        assert response.json()["items"][0]["can_acknowledge"] is False
    else:
        assert response.status_code == 403 or response.json()["total"] == 0
    assert acknowledge(client, item).status_code in {403, 404}


def test_closed_cases_and_future_schedules_do_not_alert(monitoring_api):
    client, factory, _ = monitoring_api
    row = monitored(client)
    assert client.get(ATTENTION).json()["total"] == 0
    overdue(factory, row)
    with factory() as session:
        session.get(NetworkCaseRow, "case").response_phase = "closed"
        session.commit()
    assert client.get(ATTENTION).json()["total"] == 0


def test_comparison_is_case_scoped_and_does_not_expose_contact(monitoring_api):
    client, factory, _ = monitoring_api
    first = change(client, monitored(client), "declined").json()
    continued = decide(client, first).json()
    child = continued["monitoring_decision"]["next_request_id"]
    response = client.get(BASE + "/" + child + "/comparison")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["previous"]["request_id"] == first["request_id"]
    assert value["current"]["request_id"] == child
    assert value["comparison_is_automated"] is False
    assert "INTERNAL" not in response.text and "reporter_phone" not in response.text
    assert (
        client.get(BASE + "/" + child + "/comparison?previous_id=" + child).status_code == 422
    )
    assert (
        client.get(BASE + "/" + child + "/comparison?previous_id=" + "f" * 32).status_code
        == 404
    )
    assert client.get(
        "/network/cases/other/drone-requests/" + child + "/comparison"
    ).status_code in {403, 404}
    with factory() as session:
        assert session.get(IncidentRow, "case").report_json == {"secret": "INTERNAL"}


def test_multiple_attention_items_recheck_revision(monitoring_api):
    client, factory, _ = monitoring_api
    row = monitored(client)
    with factory() as session:
        stored = session.get(CaseDroneRequestRow, row["request_id"])
        stored.payload_json = {
            **stored.payload_json,
            "outcome": "escalation_needed",
            "review_note": "Coordinator review required",
            "next_review_at": "2020-01-01T00:00:00Z",
        }
        session.commit()
    items = client.get(ATTENTION).json()["items"]
    assert [x["kind"] for x in items] == ["escalation", "overdue"]
    assert acknowledge(client, items[0]).status_code == 200
    assert acknowledge(client, items[1]).status_code == 409
    refreshed = client.get(ATTENTION).json()["items"][0]
    assert acknowledge(client, refreshed).status_code == 200
    assert client.get(ATTENTION).json()["total"] == 0
