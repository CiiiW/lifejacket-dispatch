"""Mission checks and HTTP simulation gates without a cloud account or vehicle."""

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.drones.planner import demo_mission, plan_mission
from lifejacket.drones.simulator import MockSimulator
from lifejacket.models.drone import DronePoint, SurveyBox


def test_nominal_trace_returns_home_and_preserves_reserve():
    mission = demo_mission()
    plan = plan_mission(mission)
    assert plan.status == "ready_for_review"
    assert 0 < plan.distance_m < plan.limits.max_route_m
    result = MockSimulator().run(plan, "nominal", "Local reviewer")
    final = result.samples[-1]
    assert result.status == "completed" and final.phase == "land"
    assert (final.latitude, final.longitude, final.altitude_m) == (
        mission.home.latitude,
        mission.home.longitude,
        0,
    )
    assert final.battery_percent >= plan.limits.reserve_percent
    assert [sample.elapsed_s for sample in result.samples] == sorted(
        sample.elapsed_s for sample in result.samples
    )
    assert result.samples == MockSimulator().run(plan, "nominal", "Local reviewer").samples


def test_exclusion_crossing_is_detected_without_a_waypoint_inside():
    mission = demo_mission()
    # This thin strip crosses a survey row between its west/east endpoints.
    zone = SurveyBox(south=36.8007, north=36.8009, west=-121.7992, east=-121.7988)
    mission.exclusion_zones = [zone]
    plan = plan_mission(mission)
    assert not any(
        zone.south <= p.latitude <= zone.north and zone.west <= p.longitude <= zone.east
        for p in plan.waypoints
    )
    assert plan.status == "blocked"
    assert any("exclusion" in reason for reason in plan.blocked_reasons)
    with pytest.raises(ValueError, match="Blocked"):
        MockSimulator().run(plan, "nominal", "Reviewer")


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"altitude_m": 150}, "altitude"),
        ({"simulated_wind_mps": 12}, "wind"),
        ({"home": DronePoint(latitude=40, longitude=-122)}, "distance from home"),
        (
            {"survey_area": SurveyBox(south=36.8008, north=36.808, west=-121.8, east=-121.79)},
            "budget",
        ),
    ],
)
def test_invalid_demo_missions_are_blocked(change, reason):
    plan = plan_mission(demo_mission().model_copy(update=change))
    assert plan.status == "blocked"
    assert any(reason in item for item in plan.blocked_reasons)


@pytest.mark.parametrize("scenario", ["link_loss", "low_battery"])
def test_injected_fault_stops_trace_without_claiming_recovery(scenario):
    result = MockSimulator().run(plan_mission(demo_mission()), scenario, "Reviewer")
    assert result.status == "aborted" and result.events[-1].kind == scenario
    assert result.samples[-1].phase != "land"
    assert "not modeled" in result.events[-1].message


def test_http_contract_requires_review_and_rejects_hardware_and_stale_plans():
    client = TestClient(app)
    mission = client.get("/drones/demo").json()
    plan = client.post("/drones/plan", json=mission).json()
    payload = {"mission": mission, "plan_id": plan["plan_id"], "reviewed_by": "Reviewer"}
    assert client.post("/drones/simulate", json=payload).status_code == 200
    assert (
        client.post("/drones/simulate", json={**payload, "reviewed_by": " "}).status_code
        == 422
    )
    assert (
        client.post("/drones/simulate", json={**payload, "backend": "hardware"}).status_code
        == 422
    )
    assert (
        client.post("/drones/simulate", json={**payload, "backend": "sitl"}).status_code == 422
    )
    assert (
        client.post("/drones/simulate", json={**payload, "device": "/dev/ttyUSB0"}).status_code
        == 422
    )
    mission["altitude_m"] = 70
    assert client.post("/drones/simulate", json=payload).status_code == 409
    mission["mode"] = "hardware"
    assert client.post("/drones/plan", json=mission).status_code == 422


def test_coordinates_and_unknown_controls_fail_validation():
    client = TestClient(app)
    mission = demo_mission().model_dump()
    mission["survey_area"]["south"] = mission["survey_area"]["north"]
    assert client.post("/drones/plan", json=mission).status_code == 422
    mission = demo_mission().model_dump()
    mission["reserve_percent"] = 0
    assert client.post("/drones/plan", json=mission).status_code == 422


def test_server_profile_change_invalidates_review_and_battery_budget(monkeypatch):
    from lifejacket.drones import planner

    client = TestClient(app)
    mission = demo_mission().model_dump()
    original = plan_mission(demo_mission())
    limits = original.limits.model_dump()
    limits["endurance_s"] = 120
    monkeypatch.setattr(planner, "load_drone_simulation_config", lambda: limits)
    changed = plan_mission(demo_mission())
    assert changed.status == "blocked"
    assert any("battery reserve" in reason for reason in changed.blocked_reasons)
    assert changed.plan_id != original.plan_id
    response = client.post(
        "/drones/simulate",
        json={
            "mission": mission,
            "plan_id": original.plan_id,
            "reviewed_by": "Reviewer",
        },
    )
    assert response.status_code == 409
