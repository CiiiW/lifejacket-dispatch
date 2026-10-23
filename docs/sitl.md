# ArduPilot SITL: mission upload verified

Implemented: reviewed Drone Lab plan → integer MAVLink mission → upload
acknowledgment → download/readback comparison. No arming or flight execution.
The web API remains mock-only.

## Verified on GCP, 22 October 2026

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

Supervised start, actual simulated telemetry, mission completion and abort/recovery
handling, then integration with Drone Lab. Upload/readback is an integration check,
not a validated flight or a substitute for real observations in the project study.

References:
- https://ardupilot.org/dev/docs/mavlink-mission-upload-download.html
- https://mavlink.io/en/services/mission.html
- https://firmware.ardupilot.org/Copter/stable-4.6.3/SITL_x86_64_linux_gnu/
