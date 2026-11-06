# ruff: noqa: F811
# Imported pytest fixtures are injected by parameter name.
"""Suggestions use explicit evidence, stay read-only, and require coordinator review."""

from types import SimpleNamespace

import pytest
from lifejacket.config import settings
from lifejacket.models.tables import CaseDroneRequestRow, IncidentRow, NetworkCaseRow
from lifejacket.services.drone_suggestions import group_confidence, suggest
from sqlalchemy import func, select
from test_drone_requests import drone_api, payload  # noqa: F401
from test_network_actions import api  # noqa: F401

BASE = "/network/cases/case/drone-requests"


def identity(*scores, group="pinniped"):
    return {
        "candidates": [
            {"common_name": f"Species {i}", "animal_group": group, "confidence": value}
            for i, value in enumerate(scores)
        ]
    }


def incident(**changes):
    fields = dict(
        status="awaiting_dispatch",
        duplicate_of=None,
        identification_json=None,
        assessment_json=None,
        latitude=36.8,
        longitude=-121.79,
        severity_level="monitor",
        entanglement_present=False,
    )
    return SimpleNamespace(**(fields | changes))


@pytest.mark.parametrize("confidence", [0.0, 0.62, 0.899])
def test_explicit_low_group_confidence_suggests_verification(confidence):
    item = suggest(incident(identification_json=identity(confidence)), 0.90)
    assert item["purpose"] == "verification"
    assert item["signals"][0]["confidence"] == confidence
    assert item["threshold_is_validated"] is False


def test_broader_group_confidence_avoids_unnecessary_species_verification():
    assert group_confidence(identity(0.50, 0.45)) == 0.95
    assert suggest(incident(identification_json=identity(0.50, 0.45)), 0.90) is None
    assert suggest(incident(identification_json=identity(0.90)), 0.90) is None
    # A split across response groups matters, unlike a split within one group.
    value = identity(0.50, 0.45)
    value["candidates"][1]["animal_group"] = "cetacean"
    assert suggest(incident(identification_json=value), 0.90) is not None


def test_low_condition_confidence_matters_even_with_confident_identity():
    item = suggest(
        incident(
            identification_json=identity(0.98),
            assessment_json={"injury": {"confidence": 0.58}},
        ),
        0.90,
    )
    assert [s["code"] for s in item["signals"]] == ["condition_uncertain"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"injury": {}},
        {"injury": {"confidence": None}},
        {"injury": {"confidence": "0.5"}},
        {"injury": {"confidence": True}},
        {"injury": {"confidence": float("nan")}},
    ],
)
def test_missing_or_invalid_condition_scores_are_not_zero_confidence(value):
    assert suggest(incident(assessment_json=value), 0.90) is None


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        identity(1.2),
        identity(float("nan")),
        identity(True),
        identity("0.5"),
        identity(0.7, 0.7),
        {"resolution": {"rank": "species", "animal_group": "pinniped", "confidence": 0.5}},
    ],
)
def test_invalid_or_species_only_identity_scores_do_not_invent_group_uncertainty(value):
    assert suggest(incident(identification_json=value), 0.90) is None


@pytest.mark.parametrize(
    "status", ["intake", "identifying", "assessing", "resolved", "cancelled"]
)
def test_incomplete_or_finished_incidents_do_not_suggest_a_request(status):
    assert suggest(incident(status=status, identification_json=identity(0.6)), 0.90) is None


def test_provisional_threshold_config_is_independent_and_changes_fingerprint():
    row = incident(identification_json=identity(0.85))
    assert suggest(row, 0.80) is None
    assert suggest(row, 0.90)["suggestion_id"] != suggest(row, 0.95)["suggestion_id"]
    assert (
        suggest(incident(duplicate_of="other", identification_json=identity(0.6)), 0.90)
        is None
    )


def seed(factory, **changes):
    with factory() as session:
        row = session.get(IncidentRow, "case")
        row.identification_json = identity(0.62)
        row.assessment_json = {"injury": {"confidence": 0.98}}
        for key, value in changes.items():
            setattr(row, key, value)
        session.commit()


def test_get_suggestions_is_read_only_and_review_creates_one_audited_request(drone_api):
    client, factory, _ = drone_api
    seed(factory)
    result = client.get(BASE)
    assert result.status_code == 200
    item = result.json()["suggestions"][0]
    assert "no-store" in result.headers["cache-control"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CaseDroneRequestRow)) == 0
    body = payload()
    body["suggestion_id"] = item["suggestion_id"]
    response = client.post(BASE, json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "requested"
    assert created["suggestion_snapshot"]["signals"] == item["signals"]
    assert client.get(BASE).json()["suggestions"] == []
    body["request_key"] = "retry-from-another-tab"
    retry = client.post(BASE, json=body)
    assert retry.status_code == 201 and retry.json()["request_id"] == created["request_id"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CaseDroneRequestRow)) == 1
        assert session.get(NetworkCaseRow, "case").response_phase == "received"


def test_stale_suggestion_is_rechecked_at_creation(drone_api):
    client, factory, _ = drone_api
    seed(factory)
    old = client.get(BASE).json()["suggestions"][0]
    seed(factory, identification_json=identity(0.97))
    body = payload()
    body["suggestion_id"] = old["suggestion_id"]
    assert client.post(BASE, json=body).status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CaseDroneRequestRow)) == 0


def test_urgent_response_is_not_replaced_and_closed_case_hides_suggestions(drone_api):
    client, factory, _ = drone_api
    seed(factory, severity_level="critical")
    item = client.get(BASE).json()["suggestions"][0]
    assert item["urgent_parallel_review"] and "do not wait" in item["response_note"]
    with factory() as session:
        session.get(NetworkCaseRow, "case").response_phase = "closed"
        session.commit()
    assert client.get(BASE).json()["suggestions"] == []


def test_rejected_suggestion_does_not_loop_and_new_evidence_can_suggest_again(drone_api):
    client, factory, _ = drone_api
    seed(factory)
    body = payload()
    body["suggestion_id"] = client.get(BASE).json()["suggestions"][0]["suggestion_id"]
    created = client.post(BASE, json=body).json()
    result = client.patch(
        BASE + "/" + created["request_id"],
        json={
            "revision": 0,
            "status": "declined",
            "confirmed": True,
            "note": "Ground observation is more suitable",
        },
    )
    assert result.status_code == 200
    assert client.get(BASE).json()["suggestions"] == []
    seed(factory, identification_json=identity(0.55))
    assert client.get(BASE).json()["suggestions"][0]["suggestion_id"] != body["suggestion_id"]


def test_threshold_override_is_used_by_api(drone_api, monkeypatch):
    client, factory, _ = drone_api
    seed(factory)
    monkeypatch.setattr(settings, "drone_verification_confidence_threshold", 0.60)
    assert client.get(BASE).json()["suggestions"] == []


def test_existing_manual_verification_request_suppresses_duplicate_suggestion(drone_api):
    client, factory, _ = drone_api
    seed(factory)
    assert client.get(BASE).json()["suggestions"]
    result = client.post(BASE, json=payload())
    assert result.status_code == 201
    assert client.get(BASE).json()["suggestions"] == []


def test_malformed_group_metadata_never_crashes_suggestions():
    bad = {"candidates": [{"confidence": 0.5, "animal_group": []}]}
    assert suggest(incident(identification_json=bad), 0.90) is None

def test_probability_pooling_does_not_trigger_on_float_roundoff_at_threshold():
    assert suggest(incident(identification_json=identity(0.3, 0.6)), 0.90) is None
