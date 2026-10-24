# Raspberry Pi Companion Computer (Detailed Design)

Status: proposal. Extends `docs/drone_integration.md` — this fills in the
"how" for integration points 1 and 2 (multi-angle visual input, and the
deterministic drone dispatch decision) at the hardware/firmware level.

Implementation update: [the current architecture](drone_architecture.md) starts
with a local synthetic planner and mock replay, then an ArduPilot SITL adapter.
No Pi, MAVLink transport or physical arming is implemented. Hardware/operating
assumptions below remain proposals; a universal marine-mammal approach floor
must not be treated as validated drone authorization.

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
| Low-light add-ons (optional) | Thermal camera and/or NoIR camera with IR illuminator | A different kind of signal than the visible camera, not just more pixels — see Low-light and night operation below |
| Connectivity | Wi-Fi near the drone base; LTE/cellular HAT for flights beyond Wi-Fi range | Determines whether frames stream live or buffer for upload on return — see Uplink below |
| GPS | None needed on the Pi | Flight controller already has GPS; Pi reads position over MAVLink telemetry instead of duplicating hardware |

## Software on the Pi

- **MAVLink client** (`pymavlink`): uploads the mission, arms/monitors the
  flight, reads telemetry (position, battery, link health).
- **Mission receiver**: a small service that polls or subscribes to the
  backend for a flight plan from `drone_dispatch.py`, and converts it into
  a MAVLink mission (waypoints + loiter + RTL) plus geofence parameters.
- **Local safety check**: before arming, the Pi independently re-validates
  the operator-approved wildlife constraints against the received waypoints. This is
  defense in depth — the Pi is the last software gate before a physical
  flight, so it does not simply trust that the backend's check already ran
  correctly.
- **Camera capture service**: records video (and thermal/night-vision
  frames, if those cameras are installed) during the loiter phase over the
  animal, tagging frames with GPS position and timestamp pulled from
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

## Low-light and night operation (optional add-on)

Two different pieces of hardware, often confused with each other, cover
this: a **thermal camera** detects thermal radiation without visible light;
fog performance needs separate validation. Small sensors may give only a heat blob, not
enough detail to identify species or see a wound. **Night vision** here
means an IR-sensitive (NoIR) camera paired with an infrared illuminator;
it gives an actual visual image in the dark, grayscale but with real
detail, closer to what `agents/identification.py` and
`agents/assessment.py` already expect. The realistic pairing for an actual
night flight is thermal to find and confirm a live animal, then NoIR plus
IR illuminator for the visual detail.

Hardware: a FLIR Lepton 3.5 breakout (roughly $200–250) or an MLX90640
(roughly $60–70, much lower resolution) for thermal; a Pi NoIR Camera
Module (about the same price as the regular camera) plus a basic IR
illuminator LED array (roughly $15–40) for night vision.

Software: `camera_capture.py` records these as separate streams aligned by
GPS/timestamp, not blended into the main visible feed, so
`agents/assessment.py` can reason about appearance and heat signature as
distinct signals rather than one merged image.

### Is this practical, and is it useful?

**Legally, yes, more easily than expected.** The FAA dropped the Part 107
night-flight waiver requirement in April 2021. Night flight needs no
special waiver now, just anti-collision lighting visible from 3 statute
miles (strobing 40–100 times per minute) and a pilot who's completed the
night-ops training, which is built into the current Part 107 exam.

**Technically, it's a close-range confirmation tool, not a search tool.**
The FLIR Lepton 3.5 is 160x120 pixels. At 30m altitude that's roughly
20cm/pixel ground resolution, and it degrades fast with height, by 80m
it's closer to half a meter per pixel. An animal-sized heat source is a
small handful of pixels up close and a faint blob past about 100m. The IR
illuminator's effective range is similarly short, tens of meters. Neither
is a way to scan a dark coastline from altitude; both only help once the
drone is already near a known location.

**Whether it's useful depends on something outside the drone entirely: do
the rescue centers we're working with even dispatch human responders at
night?** The California Wildlife Center states outright, "For safety
reasons, we do not perform rescues in the dark." Other stranding-network
sites checked follow the same pattern (a 48-hour monitoring window,
waiting for a safer or more accessible moment rather than responding
immediately). If the organizations in our network hold to daylight-only
response regardless of what a drone sees, then night capability doesn't
"enable a nighttime rescue." Its real value is narrower and more honest:
**confirm the animal's status and exact location overnight so the
daylight response is faster and better-informed**, rather than responders
starting a search cold at first light.

This is worth confirming with whoever on the team has talked directly to
the rescue centers, since it changes how this would be pitched, and it's
why this whole section is marked optional rather than core: the base
visible-camera integration in `drone_integration.md` already answers the
project's core accuracy gap on its own.

## How this plugs into the existing design

```
drone_dispatch.py (backend)        →  flight plan (waypoints, loiter point,
                                        site/species/activity constraints, RTL)
        ↓
mission_client.py (Pi)             →  converts plan to MAVLink mission
        ↓
safety_check.py (Pi)               →  re-validates operator-approved wildlife constraints before arming
        ↓
flight controller (ArduPilot)      →  flies the mission
        ↓
camera_capture.py (Pi)             →  records + tags frames during loiter
                                        (visible, plus thermal/night-vision
                                        if installed)
        ↓
uplink.py (Pi)                     →  streams or buffers frames
        ↓
context/drone.py (backend)         →  ingests frames
        ↓
agents/identification.py,
agents/assessment.py (backend)     →  visible frames look like an
                                        additional photo source; thermal
                                        and night-vision frames are
                                        separate aligned inputs
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
| + Thermal camera add-on | +$60–250 | MLX90640 at the low end, FLIR Lepton 3.5 breakout at the high end |
| + Night vision add-on (NoIR camera + IR illuminator) | +$40–70 | Cheaper than thermal; NoIR camera is similar cost to the regular camera, illuminator is the main add |

## Suggested module additions

| You want to... | Add |
| --- | --- |
| Convert a backend flight plan into a MAVLink mission | `companion/mission_client.py` (runs on the Pi) |
| Re-check the operator-approved wildlife constraints on-device before arming | `companion/safety_check.py` (runs on the Pi) |
| Record and tag video during loiter (visible, thermal, night-vision) | `companion/camera_capture.py` (runs on the Pi) |
| Stream or buffer frames to the backend | `companion/uplink.py` (runs on the Pi) |
| Ingest frames on the backend side | `backend/lifejacket/context/drone.py` (as already proposed in `drone_integration.md`) |

## Open questions specific to hardware

| Question | Why it matters |
| --- | --- |
| Which flight controller/airframe will the team actually use or buy? | Pixhawk + ArduPilot is the standard open path with SITL support; a different stack changes the MAVLink assumptions above |
| Hardware budget and availability before graduation (Dec 2026)? | SITL work can proceed without hardware, but a live demo needs an actual airframe sourced in time |
| Cellular connectivity cost/availability for the demo area? | Decides whether `uplink.py` needs to support the buffer-and-upload-on-return path for the actual demo, or can assume live Wi-Fi the whole time |
| Do our actual rescue center contacts dispatch responders at night? | Decides whether low-light/night capability is worth the added cost and complexity, and how it should be pitched (overnight monitoring, not nighttime rescue) |
| Is low-light/night operation in scope for v1, or a stretch goal? | Adds cost, weight, and extra signal types `agents/assessment.py` needs to reason about; the base visible-camera integration stands on its own without it |
