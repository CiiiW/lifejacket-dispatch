import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lifejacket.drones.flight import FlightRecorder, route_deviation_m
from lifejacket.drones.planner import demo_mission, plan_mission
from lifejacket.drones.runs import load_run, reconcile_interrupted, run_path, save_run


def test_saved_run_is_atomic_and_interrupted_never_resumes(tmp_path):
    run = {"run_id": uuid.uuid4().hex, "status": "flying", "samples": [], "events": []}
    save_run(tmp_path, run)
    assert not list(tmp_path.glob("*.tmp"))
    assert reconcile_interrupted(tmp_path) == 1
    assert load_run(tmp_path, run["run_id"])["status"] == "interrupted"
    assert reconcile_interrupted(tmp_path) == 0
    with pytest.raises(ValueError):
        run_path(tmp_path, "../secret")


def test_deviation_is_distance_to_segment_not_nearest_waypoint():
    plan = plan_mission(demo_mission())
    a, b = plan.waypoints[2:4]
    assert route_deviation_m(a.latitude, (a.longitude + b.longitude) / 2, plan) < 0.01
    assert route_deviation_m(36.81, -121.79, plan) > 100


def test_unknown_battery_is_not_fabricated_and_wrong_sources_ignored(tmp_path):
    link = Mock(target_system=1, target_component=1)
    plan = plan_mission(demo_mission())
    recorder = FlightRecorder(link, plan, tmp_path, "Charlotte")
    position = SimpleNamespace(
        get_type=lambda: "GLOBAL_POSITION_INT",
        get_srcSystem=lambda: 1,
        get_srcComponent=lambda: 1,
        lat=368000000,
        lon=-1218010000,
        relative_alt=60000,
        time_boot_ms=15000,
    )
    link.recv_match.return_value = position
    recorder.pump()
    assert recorder.run["samples"][-1]["battery_percent"] is None
    position.get_srcSystem = lambda: 2
    recorder.pump()
    assert len(recorder.run["samples"]) == 1
    saved = recorder.finish("unconfirmed", "test loss")
    assert saved["status"] == "unconfirmed"
    assert (
        json.loads(run_path(tmp_path, saved["run_id"]).read_text())["metrics"][
            "max_altitude_m"
        ]
        == 60
    )


def test_low_battery_requests_rtl_and_requires_landing(tmp_path, monkeypatch):
    import lifejacket.drones.flight as flight

    plan = plan_mission(demo_mission())
    recorder = FlightRecorder(Mock(target_system=1, target_component=1), plan, tmp_path, "C")
    recorder.gps_fix = 3
    recorder.run["samples"] = [
        {
            "latitude": 36.8,
            "longitude": -121.801,
            "altitude_m": 0,
            "elapsed_s": 0,
            "time_boot_ms": 0,
            "route_deviation_m": 0,
        }
    ]
    monkeypatch.setattr(flight, "upload_mission", lambda *_: None)
    monkeypatch.setattr(recorder, "parameter", lambda *_: None)
    monkeypatch.setattr(recorder, "set_mode", lambda mode: setattr(recorder, "mode", mode))
    commands = []

    def command(number, *params):
        commands.append((number, params))
        if number == 400:
            recorder.armed = recorder.ever_armed = True
        if number == 20:
            recorder.mode = 6

    def pump(*_):
        sample = recorder.run["samples"][-1].copy()
        sample.update(
            altitude_m=10 if recorder.ever_armed and not recorder.cancelled else 0,
            elapsed_s=sample["elapsed_s"] + 1,
            time_boot_ms=sample["time_boot_ms"] + 1000,
        )
        recorder.run["samples"].append(sample)
        recorder.battery = 10
        if recorder.cancelled:
            recorder.armed = False

    monkeypatch.setattr(recorder, "command", command)
    monkeypatch.setattr(recorder, "pump", pump)
    result = recorder.execute()
    assert (20, ()) in commands
    assert result["status"] == "aborted"
    assert result["outcome"] == "RTL landed and disarmed"


def test_cancellation_before_arming_never_arms(tmp_path, monkeypatch):
    plan = plan_mission(demo_mission())
    recorder = FlightRecorder(Mock(target_system=1, target_component=1), plan, tmp_path, "C")
    recorder.gps_fix = 3
    recorder.run["samples"] = [
        {
            "latitude": 36.8,
            "longitude": -121.801,
            "altitude_m": 0,
            "elapsed_s": 0,
            "time_boot_ms": 0,
            "route_deviation_m": 0,
        }
    ]
    monkeypatch.setattr(recorder, "pump", lambda *_: None)
    result = recorder.execute(cancel_requested=lambda: True)
    assert result["status"] == "aborted"
    recorder.link.mav.command_long_send.assert_not_called()
