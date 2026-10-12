undefined# Raspberry Pi Companion Computer (Detailed Design)

Status: proposal. Extends `docs/drone_integration.md` — this fills in the
"how" for integration points 1 and 2 (multi-angle visual input, and the
deterministic drone dispatch decision) at the hardware/firmware level.

## Role in the system

The Pi does not fly the drone, and it does not decide whether to fly.
Those are two other components' jobs:

- The **flight controller** (a dedicated autopilot board) handles
  stabilization, GPS hold, and waypoint navigation. This is existing,
  well-tested firmware (ArduPilot or PX4) — not something to build.
- `dispatch/drone_dispatch.py` on the backend (per `drone_integration.md`)
  decides *whether* a flight happens and produces the flight plan.
- The **Raspberry Pi** is the bridge between the two: it receives the
  flight plan from the backend, hands it to the flight controller as a
  mission, supervises execution, captures video, and gets the result back
  to the backend.

This split matters for the same reason the backend's model/function split
matters: each piece stays independently testable, and a flight failure is
attributable to a specific layer instead of "the drone misbehaved."

## Hardware stack

| Component | Choice | Why |
| --- | --- | --- |
| Flight controller | Pixhawk-class board running ArduPilot | Open, well-documented, has a software-in-the-loop (SITL) simulator — see below |
| Companion computer | Raspberry Pi Zero 2 W (weight-constrained) or Pi 4/5 (if onboard inference is needed later) | Zero 2 W keeps payload light; upgrade only if the Pi needs to run real compute, not just I/O |
| Camera | Pi Camera Module (CSI) or USB camera | Feeds `context/drone.py` the same way a reporter's phone photo feeds the pipeline today |
| Connectivity | Wi-Fi near the drone base; LTE/cellular HAT for flights beyond Wi-Fi range | Determines whether frames stream live or buffer for upload on return — see Uplink below |
| GPS | None needed on the Pi | Flight controller already has GPS; Pi reads position over MAVLink telemetry instead of duplicating hardware |

## Software on the Pi

- **MAVLink client** (`pymavlink`): uploads the mission, arms/monitors the
  flight, reads telemetry (position, battery, link health).
- **Mission receiver**: a small service that polls or subscribes to the
  backend for a flight plan from `drone_dispatch.py`, and converts it into
  a MAVLink mission (waypoints + loiter + RTL) plus geofence parameters.
- **Local safety check**: before arming, the Pi independently re-validates
  the MMPA approach-distance floor against the received waypoints. This is
  defense in depth — the Pi is the last software gate before a physical
  flight, so it does not simply trust that the backend's check already ran
  correctly.
- **Camera capture service**: records video during the loiter phase over
  the animal, tagging frames with GPS position and timestamp pulled from
  MAVLink telemetry (not from the Pi's own clock/location, which could be
  wrong or stale).
- **Uplink service**: streams frames live to `context/drone.py` when
  connectivity allows; otherwise buffers to local storage and uploads on
  return to base. Either way, the backend sees the same frame format —
  connectivity only changes latency, not the pipeline.
- **Watchdog**: lost-link and low-battery failsafes are the flight
  controller's job (RTL is a built-in ArduPilot behavior), but on telemetry
  loss the Pi should also stop issuing new commands and flag the incident
  for coordinator review rather than silently retrying.

## How this plugs into the existing design

```
drone_dispatch.py (backend)        →  flight plan (waypoints, loiter point,
                                        altitude/distance floor, RTL)
        ↓
mission_client.py (Pi)             →  converts plan to MAVLink mission
        ↓
safety_check.py (Pi)               →  re-validates MMPA floor before arming
        ↓
flight controller (ArduPilot)      →  flies the mission
        ↓
camera_capture.py (Pi)             →  records + tags frames during loiter
        ↓
uplink.py (Pi)                     →  streams or buffers frames
        ↓
context/drone.py (backend)         →  ingests frames
        ↓
agents/identification.py,
agents/assessment.py (backend)     →  unchanged — frames look like an
                                        additional photo source
```

## Development without hardware

**What SITL is:** Software In The Loop — ArduPilot's own simulator. It
runs the actual autopilot firmware as a program on a laptop instead of on
a physical Pixhawk, and simulates the drone around it (GPS position,
battery drain, sensor readings, wind). From the Pi's side nothing changes:
`mission_client.py` talks to "the flight controller" over MAVLink the same
way whether that's a real Pixhawk in the air or SITL running as a local
process on `localhost` — same protocol, same commands (upload mission,
arm, monitor telemetry).

The project already has a pattern for this: `llm/fake.py` stands in for
Gemini in tests so the rest of the pipeline can be exercised without
credentials. SITL (typically paired with MAVProxy, and viewed through
Mission Planner or QGroundControl so you can watch the simulated drone fly
the mission on a map) is the hardware equivalent: `mission_client.py` and
`safety_check.py` can be built and tested against it well before any
physical drone is available, and at zero hardware cost. This is the
concrete answer to the open question already in `drone_integration.md`
about live vs. simulated flights: simulate first, move to real hardware
only once the pipeline works end-to-end in SITL.

## Hardware cost estimate

Rough pricing as of October 2026, for budgeting purposes only — not a
purchase recommendation yet (see open questions below). None of this is
needed to start: the SITL path above is free, and should come first
regardless of which hardware option the team lands on.

| Approach | Est. cost | Notes |
| --- | --- | --- |
| Budget: clone Pixhawk 2.4.8 + Pi Zero 2 W + camera, frame/motors/battery sourced separately | $150–250 | Cheaper but clone flight controllers vary in quality and support |
| Reliable: genuine Holybro Pixhawk 6C + Pi + camera + frame/motors/battery as separate parts | $400–600 | Pixhawk 6C alone runs $199–253 depending on power module/case |
| All-in-one kit (e.g. RobotShop VAZ10 Drone Development Kit) + Pi/camera add-on | ~$450 | Kit itself is $399 and includes frame + build; ships with a RadioLink controller, not the Pixhawk assumed elsewhere in this doc |

## Suggested module additions

| You want to... | Add |
| --- | --- |
| Convert a backend flight plan into a MAVLink mission | `companion/mission_client.py` (runs on the Pi) |
| Re-check the MMPA floor on-device before arming | `companion/safety_check.py` (runs on the Pi) |
| Record and tag video during loiter | `companion/camera_capture.py` (runs on the Pi) |
| Stream or buffer frames to the backend | `companion/uplink.py` (runs on the Pi) |
| Ingest frames on the backend side | `backend/lifejacket/context/drone.py` (as already proposed in `drone_integration.md`) |

## Open questions specific to hardware

| Question | Why it matters |
| --- | --- |
| Which flight controller/airframe will the team actually use or buy? | Pixhawk + ArduPilot is the standard open path with SITL support; a different stack changes the MAVLink assumptions above |
| Hardware budget and availability before graduation (Dec 2026)? | SITL work can proceed without hardware, but a live demo needs an actual airframe sourced in time |
| Cellular connectivity cost/availability for the demo area? | Decides whether `uplink.py` needs to support the buffer-and-upload-on-return path for the actual demo, or can assume live Wi-Fi the whole time |
