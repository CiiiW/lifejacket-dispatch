"""Verify a case patrol with an isolated, short-lived ArduCopter simulator."""

import os
import subprocess
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from lifejacket.drones.sitl import mission_items, readback_mission, upload_mission
from lifejacket.models.drone import DronePlan

_upload_lock = Lock()


def simulator_binary() -> Path | None:
    configured = os.environ.get("LIFEJACKET_PATROL_SITL_BINARY")
    if configured:
        binary = Path(configured)
        if binary.is_absolute() and binary.is_file() and os.access(binary, os.X_OK):
            return binary
    return None


class SimulatorBusyError(RuntimeError):
    pass


def verify_patrol_upload(binary: Path, plan: DronePlan, reviewed_plan_id: str) -> int:
    # Optional dependency for hosts that opt in to the simulator.
    from pymavlink import mavutil

    items = mission_items(plan, reviewed_plan_id)
    home = plan.mission.home
    if not _upload_lock.acquire(blocking=False):
        raise SimulatorBusyError("Another patrol upload is running. Try again shortly.")
    try:
        with (
            TemporaryDirectory(prefix="lifejacket-patrol-") as work,
            closing(
                mavutil.mavlink_connection("tcpin:127.0.0.1:0", source_system=255)
            ) as link,
        ):
            port = link.listen.getsockname()[1]
            # Start a fresh simulator that dials our ephemeral loopback listener.
            # No existing MAVLink endpoints or controller connections are used.
            with subprocess.Popen(
                [
                    str(binary),
                    "--model",
                    "quad",
                    "--home",
                    f"{home.latitude},{home.longitude},0,0",
                    "--serial0",
                    f"tcpclient:127.0.0.1:{port}",
                    "--serial1",
                    "none",
                    "--serial2",
                    "none",
                    "--rc-in-port",
                    "0",
                    "--irlock-port",
                    "0",
                    "--speedup",
                    "3",
                ],
                cwd=work,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            ) as process:
                try:
                    mav = mavutil.mavlink
                    deadline = time.monotonic() + 8
                    # Boot heartbeats arrive before mission storage is initialized.
                    while (remaining := deadline - time.monotonic()) > 0:
                        heartbeat = link.wait_heartbeat(timeout=min(remaining, 1))
                        if process.poll() is not None:
                            raise RuntimeError("ArduCopter exited during startup")
                        if heartbeat is None:
                            continue
                        if (
                            heartbeat.autopilot != mav.MAV_AUTOPILOT_ARDUPILOTMEGA
                            or heartbeat.type != mav.MAV_TYPE_QUADROTOR
                            or heartbeat.base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED
                        ):
                            raise RuntimeError("Expected a disarmed ArduCopter simulator")
                        if heartbeat.system_status == mav.MAV_STATE_STANDBY:
                            break
                    else:
                        raise TimeoutError("ArduCopter did not reach standby")
                    link.target_system = heartbeat.get_srcSystem()
                    link.target_component = heartbeat.get_srcComponent()
                    upload_mission(link, items, timeout_s=3)
                    return readback_mission(link, items, timeout_s=2)
                finally:
                    # The transient simulator has no state to persist.
                    process.kill()
    finally:
        _upload_lock.release()
