# ArduPilot SITL: flight supervision and saved telemetry

Implemented: reviewed demo → mission upload → supervised AUTO flight → saved
telemetry/outcome. Upload/readback verification remains available separately.
The API exposes saved runs read-only; flight commands use a local SITL-only CLI.

## Initial upload verification on GCP, 22 October 2026

- Debian 11, x86_64, 4 CPUs, 15 GiB RAM.
- Official prebuilt ArduCopter 4.6.3; source/defaults tag `Copter-4.6.3`
  at `92b0cd788ec29406f26c6f9c315d5ceedbd1cc538`.
- Isolated Python 3.10.20 environment, pymavlink 2.4.50. The repository's
  declared application runtime remains Python >=3.11; this test exercised only
  the standalone planner and MAVLink adapter on the VM's existing interpreter.
- Invented demo mission: 16 items, accepted; downloaded navigation commands,
  latitude/longitude (within 1e-7 degree) and altitude (within 0.01 m) matched.
- Home (index zero) is reserved by ArduPilot and excluded from navigation
  equality checks. No flight was started; no dynamics/recovery claim is made.
- Eight unit tests pass, including component binding and legacy requests.

Two issues found by integration testing were fixed: pymavlink left the target
component at broadcast zero after heartbeat, and float `MISSION_ITEM` replies
lost coordinate precision. Clients now bind system/component from heartbeat;
legacy requests receive `MISSION_ITEM_INT` per current MAVLink guidance.

## GCP setup used

Run from `/home/jupyter`. Keep simulator files outside tracked application code.

```bash
mkdir -p sitl-tools/prebuilt
python -m venv sitl-tools/venv
sitl-tools/venv/bin/pip install pymavlink==2.4.50 pydantic-settings pytest
# The source checkout supplies the version-matched default parameters.
git clone --branch Copter-4.6.3 --depth 1 https://github.com/ArduPilot/ardupilot.git sitl-tools/ardupilot
curl -fL https://firmware.ardupilot.org/Copter/stable-4.6.3/SITL_x86_64_linux_gnu/arducopter -o sitl-tools/prebuilt/arducopter
chmod +x sitl-tools/prebuilt/arducopter
bash scripts/start_sitl.sh
```

In a second terminal, from the repository root:

```bash
PYTHONPATH=backend /home/jupyter/sitl-tools/venv/bin/python scripts/sitl_verify_upload.py
/home/jupyter/sitl-tools/venv/bin/python -m pytest backend/tests/test_sitl.py
```

The verification command replaces the simulator's mission with the invented
demo route. It connects only to `tcp:127.0.0.1:5760`. Use this setup only with
SITL. No firewall or application deployment changes are needed. Stop the
simulator with Ctrl-C in its terminal when done.

For a different reviewed plan, save the complete `/drones/plan` response as JSON:

```bash
PYTHONPATH=backend /home/jupyter/sitl-tools/venv/bin/python scripts/sitl_upload.py reviewed-plan.json --reviewed-plan-id PLAN_ID
```

The adapter regenerates the plan using current limits and rejects blocked,
changed or stale plans. The supplied plan must use the simulator's configured
home. Mission heights are relative to home. Upload failures leave mission state
unconfirmed; inspect before retrying. The standalone path does not independently
re-query historical dataset provenance from the application database.

## Next milestone

Next is real observation evidence ingestion and coordinator verification, plus
broader firmware failsafe tests. SITL results do not replace real observations
in the project study.

References:
- https://ardupilot.org/dev/docs/mavlink-mission-upload-download.html
- https://mavlink.io/en/services/mission.html
- https://firmware.ardupilot.org/Copter/stable-4.6.3/SITL_x86_64_linux_gnu/

## Flight worker and saved runs

`scripts/sitl_fly.py` now starts its own ArduCopter process, uploads the reviewed
invented demo, waits for GPS and normal arming checks, starts AUTO, records
telemetry and waits for landing/disarming. It refuses to attach if port 5760 is
already occupied and serializes workers using a local file lock. No force-arm or
arming-check bypass is used. Wind and cruise speed are confirmed simulator
parameters; the binary SHA-256 and acceleration factor are saved with the run.

Use Python >=3.11. The GCP test environment is now `sitl-tools/flight-venv`.

```bash
PYTHONPATH=backend /home/jupyter/sitl-tools/flight-venv/bin/python scripts/sitl_fly.py --execute-reviewed-demo --short-survey --reviewed-by Charlotte
# Controlled cancel/RTL test, measured in wall-clock seconds:
PYTHONPATH=backend /home/jupyter/sitl-tools/flight-venv/bin/python scripts/sitl_fly.py --execute-reviewed-demo --short-survey --reviewed-by Charlotte --abort-after 8
# Controlled telemetry disconnection; expected result is unconfirmed, exit 1:
PYTHONPATH=backend /home/jupyter/sitl-tools/flight-venv/bin/python scripts/sitl_fly.py --execute-reviewed-demo --short-survey --reviewed-by Charlotte --drop-link-after 8
# A second terminal can request cancellation of an active local run:
PYTHONPATH=backend /home/jupyter/sitl-tools/flight-venv/bin/python scripts/sitl_fly.py --cancel-run RUN_ID
```

SIGINT/SIGTERM request cancellation too. A pre-arm cancellation avoids arming;
a ground cancellation after arming disarms normally. In flight, cancellation or
reported battery below the plan's reserve requests RTL. Only observed low
altitude plus disarming confirms recovery; an ACK alone is insufficient. Link
loss, stale position, failed recovery or timeout never count as completion.
Injected disconnection closes the client; this test does not validate the
firmware's autonomous GCS-loss failsafe. Terminating the owned simulator during
cleanup is also not evidence of a successful recovery.

Run JSON snapshots are atomically replaced at `var/drone-runs/` (override with
`DRONE_RUNS_DIR`). They include the complete reviewed plan, measured positions,
altitude, flight mode, battery (null when unknown), mission progress, events,
route deviation and outcome. Wall time and simulated boot time are separate.
On restart, while holding the worker lock, unfinished records become
`interrupted`; the worker never resumes a previous mission automatically.

The API exposes read-only `GET /drones/runs` and `GET /drones/runs/{run_id}`.
Drone Lab polls selected runs every two seconds, overlays the measured trace
on the plan, and shows state, current telemetry, events and final metrics.
The companion and API must share the same run directory. For containers, mount
it and set `DRONE_RUNS_DIR` to its container path; copying code alone will not
make host snapshots visible. The existing deployment is not changed by this
worker. Flight commands remain local CLI actions rather than public endpoints.

These records are explicitly synthetic. No camera observations are generated,
and no rescue incident is created automatically. Real observation ingestion and
coordinator verification remain a separate evidence integration milestone.


### Flight test findings

The original large demo completed with the default simulator profile before
wind/speed were explicitly aligned. With the requested 3 m/s simulated wind and
5 m/s cruise speed, its reported battery crossed the 25% reserve and the worker
requested RTL; landing/disarming were observed. This demonstrates a mismatch
between the planner's generic 1,200-second endurance assumption and this SITL
battery model. Do not present the planner's battery estimate as calibrated.

Use `--short-survey` for the nominal smoke test: 20 m altitude, bounds
36.8002–36.8006 latitude and -121.8008–-121.8003 longitude. It retains the
same invented home and simulated wind. Omitting that flag runs the larger demo.
Both plan variants and complete measured traces are stored with their run.

The configured short survey completed, landed and disarmed on GCP: 280 samples,
about 30 wall-clock seconds (140 simulated seconds), maximum altitude 20.01 m,
and maximum horizontal distance to the nearest planned segment 1.18 m. The
controlled cancel run also landed/disarmed; injected link loss was correctly
recorded as unconfirmed. Backend offline suite: 324 passed. Responder console:
TypeScript check and production web export passed.
