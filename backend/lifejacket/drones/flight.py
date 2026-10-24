"""SITL-only mission supervision; transport and simulator lifecycle belong to CLI."""

import math
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from lifejacket.drones.planner import distance_m
from lifejacket.drones.runs import save_run
from lifejacket.drones.sitl import mission_items, upload_mission
from lifejacket.models.drone import DronePlan, DronePoint


class CommandRejected(RuntimeError):
    pass


def route_deviation_m(latitude: float, longitude: float, plan: DronePlan) -> float:
    """Horizontal distance to the nearest planned segment (local tangent plane)."""
    scale_y = math.pi * 6371008.8 / 180
    scale_x = scale_y * math.cos(math.radians(latitude))
    points = [
        ((p.longitude - longitude) * scale_x, (p.latitude - latitude) * scale_y)
        for p in plan.waypoints
    ]
    closest = float("inf")
    for (x, y), (u, v) in zip(points, points[1:], strict=False):
        dx, dy = u - x, v - y
        length = dx * dx + dy * dy
        t = max(0, min(1, -(x * dx + y * dy) / length)) if length else 0
        closest = min(closest, math.hypot(x + t * dx, y + t * dy))
    return closest


class FlightRecorder:
    def __init__(self, link, plan: DronePlan, root: Path, reviewer: str):
        self.link, self.plan, self.root = link, plan, root
        self.started = time.monotonic()
        self.last_heartbeat = self.started
        self.last_position = self.started
        self.last_sent = 0.0
        self.last_saved = 0.0
        self.armed = False
        self.ever_armed = False
        self.mode = 0
        self.gps_fix = 0
        self.battery = None
        self.seq = 0
        self.reached = set()
        self.cancelled = False
        self.run = {
            "run_id": uuid.uuid4().hex,
            "backend": "ardupilot_sitl",
            "synthetic": True,
            "plan_id": plan.plan_id,
            "plan": plan.model_dump(mode="json"),
            "reviewed_by": reviewer,
            "started_at": datetime.now(UTC).isoformat(),
            "status": "preparing",
            "outcome": None,
            "samples": [],
            "events": [],
            "metrics": {},
            "observations": [],
            "limitations": [
                "SITL telemetry is synthetic; no wildlife observations captured",
                "Route deviation is horizontal distance to nearest planned segment",
                "No physical-aircraft authorization or recovery validation",
            ],
        }
        self.flush()

    def event(self, kind, message):
        self.run["events"].append(
            {
                "elapsed_s": round(time.monotonic() - self.started, 3),
                "kind": kind,
                "message": str(message),
            }
        )
        self.flush()

    def flush(self):
        save_run(self.root, self.run)
        self.last_saved = time.monotonic()

    def pump(self, timeout=0.2):
        now = time.monotonic()
        if now - self.last_sent >= 1:
            # GCS heartbeat, not an aircraft heartbeat.
            self.link.mav.heartbeat_send(6, 8, 0, 0, 4)
            self.last_sent = now
        msg = self.link.recv_match(blocking=True, timeout=timeout)
        if msg is None:
            return None
        if (msg.get_srcSystem(), msg.get_srcComponent()) != (
            self.link.target_system,
            self.link.target_component,
        ):
            return None
        kind = msg.get_type()
        if kind == "HEARTBEAT":
            self.last_heartbeat = now
            self.armed = bool(msg.base_mode & 128)
            self.ever_armed |= self.armed
            self.mode = msg.custom_mode
        elif kind == "GPS_RAW_INT":
            self.gps_fix = msg.fix_type
        elif kind == "SYS_STATUS":
            self.battery = msg.battery_remaining if 0 <= msg.battery_remaining <= 100 else None
        elif kind == "MISSION_CURRENT":
            self.seq = msg.seq
        elif kind == "MISSION_ITEM_REACHED":
            self.reached.add(msg.seq)
            self.event("waypoint_reached", msg.seq)
        elif kind == "STATUSTEXT":
            self.event("autopilot", msg.text)
        elif kind == "GLOBAL_POSITION_INT":
            self.last_position = now
            lat, lon = msg.lat / 1e7, msg.lon / 1e7
            if not 32 <= lat <= 42.5 or not -125 <= lon <= -114:
                return msg
            seq = min(self.seq, len(self.plan.waypoints) - 1)
            self.run["samples"].append(
                {
                    "elapsed_s": round(now - self.started, 3),
                    "time_boot_ms": msg.time_boot_ms,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude_m": msg.relative_alt / 1000,
                    "battery_percent": self.battery,
                    "mode": self.mode,
                    "armed": self.armed,
                    "waypoint_seq": self.seq,
                    "phase": self.plan.waypoints[seq].phase,
                    "route_deviation_m": round(route_deviation_m(lat, lon, self.plan), 3),
                }
            )
        if now - self.last_saved > 1:
            self.flush()
        return msg

    def wait(self, predicate, seconds, message):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.pump()
            if predicate():
                return
        raise TimeoutError(message)

    def command(self, command, *params, timeout=10):
        self.link.mav.command_long_send(
            self.link.target_system,
            self.link.target_component,
            command,
            0,
            *(list(params) + [0] * (7 - len(params))),
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self.pump()
            if msg is not None and msg.get_type() == "COMMAND_ACK" and msg.command == command:
                if msg.result == 0:
                    self.event("command_accepted", command)
                    return
                if msg.result != 5:  # IN_PROGRESS is not completion.
                    raise CommandRejected(f"Command {command} rejected: {msg.result}")
        raise TimeoutError(f"No accepted acknowledgment for command {command}")

    def parameter(self, name, value):
        self.link.mav.param_set_send(
            self.link.target_system, self.link.target_component, name.encode(), value, 9
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            msg = self.pump()
            if msg is None or msg.get_type() != "PARAM_VALUE":
                continue
            param_id = (
                msg.param_id.decode() if isinstance(msg.param_id, bytes) else msg.param_id
            )
            if param_id.rstrip("\x00") == name and abs(msg.param_value - value) < 0.01:
                self.event("simulator_parameter", f"{name}={value}")
                return
        raise TimeoutError(f"Simulator parameter {name} not confirmed")

    def set_mode(self, mode):
        self.command(176, 1, mode)
        self.wait(lambda: self.mode == mode, 8, f"Mode {mode} not confirmed")

    def finish(self, status, outcome):
        samples = self.run["samples"]
        elapsed = samples[-1]["elapsed_s"] if samples else 0
        airborne = [s for s in samples if s["altitude_m"] > 2]
        last = samples[-1] if samples else None
        self.run["status"], self.run["outcome"] = status, outcome
        self.run["metrics"] = {
            "elapsed_wall_s": elapsed,
            "sample_count": len(samples),
            "elapsed_simulated_s": (
                (samples[-1]["time_boot_ms"] - samples[0]["time_boot_ms"]) / 1000
                if len(samples) > 1
                else 0
            ),
            "max_route_deviation_m": max(
                (s["route_deviation_m"] for s in airborne), default=None
            ),
            "max_altitude_m": max((s["altitude_m"] for s in samples), default=None),
            "waypoints_reached": sorted(self.reached),
            "home_distance_m": (
                round(
                    distance_m(
                        DronePoint(latitude=last["latitude"], longitude=last["longitude"]),
                        self.plan.mission.home,
                    ),
                    3,
                )
                if last
                else None
            ),
        }
        self.flush()
        return self.run

    def execute(
        self,
        *,
        timeout_s=240,
        abort_after_s=None,
        drop_link_after_s=None,
        cancel_requested=lambda: False,
    ):
        items = mission_items(self.plan, self.plan.plan_id)
        try:
            self.link.mav.request_data_stream_send(
                self.link.target_system, self.link.target_component, 0, 2, 1
            )
            self.wait(
                lambda: self.gps_fix >= 3 and bool(self.run["samples"]),
                45,
                "No valid GPS/position from SITL",
            )
            sample = self.run["samples"][-1]
            if self.armed or sample["altitude_m"] > 2:
                raise RuntimeError("Simulator must be disarmed and on the ground")
            if (
                distance_m(
                    DronePoint(latitude=sample["latitude"], longitude=sample["longitude"]),
                    self.plan.mission.home,
                )
                > 10
            ):
                raise RuntimeError("SITL home differs from reviewed plan")
            if cancel_requested():
                return self.finish("aborted", "Cancelled before arming")
            self.parameter("SIM_WIND_SPD", self.plan.mission.simulated_wind_mps)
            self.parameter("WPNAV_SPEED", self.plan.limits.cruise_speed_mps * 100)
            upload_mission(self.link, items)
            self.event("mission_uploaded", f"{len(items)} items accepted")
            self.set_mode(4)  # GUIDED permits normal arming without AUTO_OPTIONS changes.
            arm_deadline = time.monotonic() + 45
            while True:
                if cancel_requested():
                    return self.finish("aborted", "Cancelled before arming")
                try:
                    self.command(400, 1)
                    break
                except CommandRejected as exc:
                    self.event("arming_wait", exc)
                    if time.monotonic() >= arm_deadline:
                        raise
                    # Continue receiving EKF readiness/status messages.
                    until = time.monotonic() + 2
                    while time.monotonic() < until:
                        self.pump()
            self.wait(lambda: self.armed, 8, "Arming not confirmed")
            self.run["status"] = "armed"
            self.flush()
            if cancel_requested():
                self.command(400, 0)
                self.wait(lambda: not self.armed, 8, "Ground disarm not confirmed")
                return self.finish("aborted", "Cancelled and disarmed before takeoff")
            self.set_mode(3)  # AUTO, then MISSION_START releases the ground takeoff.
            self.command(300)
            self.run["status"] = "flying"
            self.event("mission_started", "AUTO mission start acknowledged")
            flight_start = time.monotonic()
            airborne = False
            while time.monotonic() - flight_start < timeout_s:
                if (
                    drop_link_after_s is not None
                    and time.monotonic() - flight_start >= drop_link_after_s
                ):
                    self.link.close()
                    self.event("test_link_loss", "Closed owned SITL telemetry connection")
                    return self.finish(
                        "unconfirmed", "Injected link loss; landing unconfirmed"
                    )
                self.pump()
                samples = self.run["samples"]
                last = samples[-1] if samples else None
                airborne |= bool(last and last["altitude_m"] > 2)
                if time.monotonic() - self.last_heartbeat > 8:
                    return self.finish(
                        "unconfirmed", "Telemetry link lost; vehicle state unknown"
                    )
                if time.monotonic() - self.last_position > 8:
                    raise TimeoutError("Position telemetry stale")
                if airborne and self.armed and self.mode in {6, 9} and not self.cancelled:
                    self.cancelled = True
                    self.run["status"] = "returning"
                    self.event(
                        "autopilot_recovery", f"Autopilot entered recovery mode {self.mode}"
                    )
                abort_reason = None
                if cancel_requested():
                    abort_reason = "Operator cancellation requested RTL"
                elif (
                    abort_after_s is not None
                    and time.monotonic() - flight_start >= abort_after_s
                ):
                    abort_reason = "Controlled test timer requested RTL"
                elif (
                    self.battery is not None
                    and self.battery < self.plan.limits.reserve_percent
                ):
                    abort_reason = f"Battery {self.battery}% below reserve requested RTL"
                if not self.cancelled and abort_reason:
                    self.cancelled = True
                    self.run["status"] = "returning"
                    self.event("abort_requested", abort_reason)
                    self.command(20)
                    self.wait(lambda: self.mode == 6, 8, "RTL mode not confirmed")
                if airborne and not self.armed and last and last["altitude_m"] < 1:
                    if self.cancelled:
                        return self.finish("aborted", "RTL landed and disarmed")
                    survey_indices = {
                        i for i, p in enumerate(self.plan.waypoints) if p.phase == "survey"
                    }
                    home_distance = distance_m(
                        DronePoint(latitude=last["latitude"], longitude=last["longitude"]),
                        self.plan.mission.home,
                    )
                    if survey_indices <= self.reached and home_distance <= 10:
                        return self.finish(
                            "completed", "Survey completed, landed and disarmed"
                        )
                    return self.finish(
                        "failed", "Landed before all survey waypoints were reached"
                    )
            raise TimeoutError("Flight deadline exceeded")
        except Exception as exc:
            self.event("error", exc)
            if self.ever_armed and self.armed:
                try:
                    self.command(20)
                    self.event("recovery", "RTL acknowledged; landing not confirmed")
                except Exception as recovery_error:
                    self.event("recovery_unconfirmed", recovery_error)
            return self.finish("unconfirmed" if self.ever_armed else "failed", str(exc))
