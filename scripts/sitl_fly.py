"""Run the invented reviewed demo against an exclusively owned local SITL process."""

import argparse
import fcntl
import hashlib
import json
import signal
import socket
import subprocess
import time
from pathlib import Path

from lifejacket.config import settings
from lifejacket.drones.flight import FlightRecorder
from lifejacket.drones.planner import demo_mission, plan_mission
from lifejacket.drones.runs import TERMINAL, load_run, reconcile_interrupted, run_path
from lifejacket.models.drone import SurveyBox
from pymavlink import mavutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-reviewed-demo", action="store_true")
    parser.add_argument(
        "--short-survey",
        action="store_true",
        help="Use a 20 m altitude, approximately 45 by 45 m survey",
    )
    parser.add_argument("--reviewed-by", default="Local SITL reviewer")
    parser.add_argument("--sitl-root", type=Path, default=Path("/home/jupyter/sitl-tools"))
    parser.add_argument("--abort-after", type=float, help="Controlled RTL after wall seconds")
    parser.add_argument(
        "--drop-link-after", type=float, help="Close telemetry after wall seconds"
    )
    parser.add_argument("--cancel-run", help="Request RTL for a local run ID")
    args = parser.parse_args()
    root = settings.drone_runs_dir
    root.mkdir(parents=True, exist_ok=True)
    if args.cancel_run:
        if load_run(root, args.cancel_run)["status"] in TERMINAL:
            parser.error("Run is already terminal")
        run_path(root, args.cancel_run).with_suffix(".cancel").touch()
        print("Cancellation requested; wait for worker acknowledgment and landing")
        return
    if not args.execute_reviewed_demo:
        parser.error("Review demo_mission() and pass --execute-reviewed-demo to run SITL")
    if not args.reviewed_by.strip() or len(args.reviewed_by) > 80:
        parser.error("Reviewer must contain 1–80 nonblank characters")
    if args.drop_link_after is not None and args.drop_link_after <= 0:
        parser.error("--drop-link-after must be positive")
    if args.abort_after is not None and args.abort_after <= 0:
        parser.error("--abort-after must be positive")
    lock = (root / "worker.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Do not attach to any preexisting autopilot, including physical-device bridges.
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 5760)) == 0:
            raise RuntimeError("Port 5760 is occupied; stop the previous simulator first")
    reconcile_interrupted(root)
    mission = demo_mission()
    if args.short_survey:
        mission = mission.model_copy(
            update={
                "altitude_m": 20.0,
                "survey_area": SurveyBox(
                    south=36.8002, north=36.8006, west=-121.8008, east=-121.8003
                ),
            }
        )
    plan = plan_mission(mission)
    work = args.sitl_root / "flight"
    work.mkdir(parents=True, exist_ok=True)
    cancelled = False

    def request_cancel(*_):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGINT, request_cancel)
    signal.signal(signal.SIGTERM, request_cancel)
    with (work / "simulator.log").open("w") as log:
        process = subprocess.Popen(
            [
                str(args.sitl_root / "prebuilt" / "arducopter"),
                "--model",
                "quad",
                "--home",
                "36.8,-121.801,0,0",
                "--speedup",
                "5",
                "--defaults",
                str(
                    args.sitl_root
                    / "ardupilot"
                    / "Tools"
                    / "autotest"
                    / "default_params"
                    / "copter.parm"
                ),
            ],
            cwd=work,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        link = None
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Owned simulator failed; inspect simulator.log")
                try:
                    link = mavutil.mavlink_connection("tcp:127.0.0.1:5760", source_system=255)
                    break
                except ConnectionRefusedError:
                    time.sleep(0.2)
            if link is None:
                raise TimeoutError("Owned SITL did not open its port")
            heartbeat = link.wait_heartbeat(timeout=15)
            if heartbeat is None or heartbeat.autopilot != 3 or heartbeat.type != 2:
                raise RuntimeError("Expected ArduPilot quadrotor heartbeat")
            link.target_system = heartbeat.get_srcSystem()
            link.target_component = heartbeat.get_srcComponent()
            recorder = FlightRecorder(link, plan, root, args.reviewed_by)
            recorder.run["environment"] = {
                "speedup": 5,
                "autopilot": "ArduCopter 4.6.3",
                "binary_sha256": hashlib.sha256(
                    (args.sitl_root / "prebuilt" / "arducopter").read_bytes()
                ).hexdigest(),
            }
            recorder.flush()
            print(f"RUN_ID={recorder.run['run_id']}", flush=True)
            cancel_file = run_path(root, recorder.run["run_id"]).with_suffix(".cancel")
            result = recorder.execute(
                abort_after_s=args.abort_after,
                drop_link_after_s=args.drop_link_after,
                cancel_requested=lambda: cancelled or cancel_file.exists(),
            )
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in result.items()
                        if k not in {"samples", "events", "plan"}
                    },
                    indent=2,
                )
            )
            if result["status"] not in {"completed", "aborted"}:
                raise SystemExit(1)
        finally:
            if link is not None:
                link.close()
            # This is an owned simulation; stopping it is not aircraft recovery.
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            lock.close()


if __name__ == "__main__":
    main()
