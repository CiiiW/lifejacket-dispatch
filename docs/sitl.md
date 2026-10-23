# ArduPilot SITL: first integration

Implemented: reviewed Drone Lab plan → MAVLink mission translation → upload
handshake → accepted/rejected/timeout result. This does not arm or execute a
flight. The web API remains mock-only. No live SITL flight has been verified.

Use a separately running local ArduCopter SITL, with home matching the plan
(e.g. demo latitude 36.8, longitude -121.801). Leave TCP port 5760 available
for this client. Only connect this development setup to SITL.

From the repository root, in the backend Python environment:

```bash
python -m pip install pymavlink
PYTHONPATH=backend python scripts/sitl_upload.py reviewed-plan.json --reviewed-plan-id PLAN_ID
```

`reviewed-plan.json` is the complete `/drones/plan` response reviewed by the
operator. The adapter regenerates it with current server limits and rejects
blocked, changed or stale plans. Home is item zero, followed by takeoff,
survey waypoints, return waypoint and land. Heights are relative to home.
The uploader handles integer and legacy mission requests, repeat requests,
invalid sequences, rejection, premature acknowledgment and timeout. Upload
failure leaves aircraft mission state unknown; inspect before retrying.

Next milestone: run this against a pinned ArduCopter SITL build; verify the
uploaded mission by download, then implement supervised start, telemetry,
completion and abort handling. Unit tests exercise the protocol with fake
messages and do not establish firmware compatibility or flight success.

Protocol reference: https://ardupilot.org/dev/docs/mavlink-mission-upload-download.html
