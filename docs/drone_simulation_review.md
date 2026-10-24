# Drone simulation source review and MVP plan

Reviewed 2026-10-19 against `charlotte` at `9dd4f0b06b248a10ba216c04cc0dbeee57342a4c`.
The connected GitHub browser was used to inspect the branch, PR #9 and drone
source/design pages; a matching Git checkout was used for the deeper code review,
branch comparison and tests. Findings below describe that baseline; the first
increment is described separately.

## Verified branch state

- PR #9 merged 23 commits from `charlotte-drone-lab` into `charlotte`.
- `git diff charlotte origin/charlotte-drone-lab` is empty at the reviewed baseline.
  The former development branch is not a second implementation to merge again.
- `git rev-list --left-right --count origin/main...charlotte` returns `0 81`:
  main contributes no newer commits to incorporate. PR #10 is visible as open.
- No AGENTS.md was found in the checkout. No merge or deployment is part of this change.

## Verified application architecture

| Layer | Actual code | Behavior |
| --- | --- | --- |
| Clients | `clients/reporter_app`, `clients/responder_console`, `clients/shared/api.ts` | React Native/Expo/TypeScript apps sharing typed HTTP access. Web console uses MapLibre; native incident maps use react-native-maps. Console includes Triage, incident evidence, coordination, handover and Drone Lab. |
| HTTP | `backend/lifejacket/api/main.py`, `api/routes/` | FastAPI mounts intake, incidents, responders, coordination, historical and drone routes. |
| Intake | `services/pipeline.py`, `chatbot/session.py`, `agents/` | Resumable photo/location conversation: detect animals, choose target/crop, identify taxonomy, assess condition, validate consistency, score severity, draft report, guardrail review, duplicate checks and responder ranking. |
| AI boundary | `llm/client.py`, `llm/fake.py`, `prompts/` | Shared Google Gen AI client and scripted offline adapter. Existing detection uses Gemini boxes, not an aerial detector trained/evaluated on drone footage. |
| Decisions | `dispatch/severity.py`, `duplicates.py`, `matching.py`, `mass_stranding.py` | Deterministic triage/rules, nearby duplicate matching and responder ranking. Geographic grouping is reusable; it is not a drone risk model. |
| Coordination | `api/routes/responders.py`, `services/coordination.py`, `agents/coordination.py` | Human assignment offers and responder accept/decline; read-only model review tools and handover. No automatic rescue dispatch. Reviewer/actor references are not authenticated identities. |
| Persistence | `models/tables.py`, `repository.py`, `db.py` | SQLAlchemy, SQLite default, Postgres staging. Indexed incident fields plus full JSON evidence; photos on disk; conversations, messages, assignments, logs, events and historical aggregates. No drone mission/run/sighting tables. Uses create_all, not migrations. |
| Environment | `context/environment.py`, `weather.py`, `tides.py`, `geocode.py`, `routing.py` | Weather/marine context, NOAA tides, geocoding and navigation; unavailable providers are explicit. These are not flight-weather or airspace validation services. |
| Local runtime | `scripts/local_demo.py`, `deploy/compose.staging.yaml`, Dockerfiles and nginx config | Local Postgres + API + exported Expo web, loopback only, persistent DB/photos and optional private NOAA import. Team origin/edge configuration also exists; no personal GCP access is required for Drone Lab. AI calls still need credentials. |

Data flow is reporter photo/location → stored conversation → detection/target
selection → identification → assessment/validation → deterministic severity →
report/guardrail → duplicate linking/responder suggestions → coordinator offer →
responder response → field logs/outcome/handover. A drone frame cannot simply
replace the active reporter photo: `attach_photo` resets prior analysis and the
pipeline expects reporter answers. Drone ingestion needs an explicit source and
review boundary.

## Drone progress and gaps at the baseline

| Capability | Status | Evidence / limitation |
| --- | --- | --- |
| NOAA workbook import | Implemented | `services/historical_strandings.py`: streamed confirmed California decimal-coordinate records dated 2006–2025, exclusion accounting, checksum and atomic replacement. Original rows are not stored. |
| Historical heatmap | Implemented | `GET /historical-strandings/density`; 0.1-degree cells, threshold 10, count bands only. Shared TriageMap heatmap. It measures report density, not calibrated risk. |
| Seasonal/environmental risk | Missing | Import discards dates/species after aggregation. No monthly features, observation-effort correction, shoreline mask, environmental join or held-out evaluation. Cannot recover seasonality from the stored cells. |
| Waypoint planning | Implemented, bounded | `drones/planner.py`: serpentine survey, takeoff/return/land, modeled range/duration/reserve, wind/altitude and supplied rectangle exclusions along all segments. No optimization around obstacles, terrain or live airspace. |
| Mission review | Implemented as demo | `/drones/plan` and `/drones/simulate` recompute and hash plan/limits. Changed/blocked plans cannot run. Typed label is an acknowledgment, not authentication or pilot clearance. |
| Flight simulation | Partial | `Simulator` protocol and `MockSimulator`: constant-speed interpolation, linear battery, injected faults stop replay. No firmware, vehicle dynamics or tested RTL recovery. |
| Coordinator UI | Partial | DroneLabScreen, DroneLabMap and shared TriageMap replay traces. Baseline uses one invented Monterey rectangle; historical layer is disconnected. |
| Aerial wildlife CV | Missing | Existing general photo detection/cropping can inform later work; no aerial dataset, aerial localization, validated detector, synthetic flight detections or frame ingestion contract. |
| Sighting review/rescue handoff | Missing | No simulation sighting queue, frame/time/run provenance, accept/reject or deduplication between sightings and incidents. |
| SITL / companion hardware | Documented only | No MAVLink dependency, SITL worker, camera service, Pi code, drone base registry, telemetry freshness checks or physical execution endpoint. |

Do not add a parallel planner, second frontend, new agent framework or cloud
fleet service. Reuse the importer, map, planner checks, review hash, simulator
seam, console and existing human dispatch workflow.

## Recommended MVP sequence and files

1. **Historical evidence → manually bounded survey → existing mock replay.**
   Extend `models/drone.py`, `api/routes/drones.py`, the existing density response,
   `clients/shared/api.ts`, DroneLabScreen/DroneLabMap/TriageMap. Add a focused
   `drones/historical.py` validator and offline tests. Reuse counts; never turn
   the aggregate center into an animal location, real base or automatic route.
2. **Synthetic sightings → coordinator review.** Add modular
   `drones/detections.py` and typed sightings with run/frame IDs, capture timestamp,
   explicit simulation provenance, vehicle position and separately labeled
   estimated target position. Use a generated fixture image, not invented model
   accuracy. Show pending/accepted/rejected sightings in Drone Lab and reveal
   them only as the trace reaches their capture times. Keep synthetic sightings
   out of real incidents/assignments; demonstrate a simulated handoff separately.
3. **Reproducible saved experiments.** Add mission/run/sighting tables via a
   migration, preserving current DBs. Record reviewed intent, source checksum,
   policy snapshot, ordered telemetry/events, decisions and idempotency keys.
   A coordinator may link a survey to a reported incident; this is distinct from
   responder assignment or authorization for a physical flight.
4. **ArduPilot SITL adapter.** Add an optional local worker owning the connection,
   with MAVLink upload acknowledgments, bounded timeouts, heartbeat/position
   freshness, observed telemetry and explicit failures. FastAPI submits jobs;
   console polls status/events and reuses the replay contract. No flight-long
   blocking HTTP handler. Keep mock as the default for teammate setup/tests.
5. **Aerial CV feasibility and risk analysis.** Test a labeled aerial set with
   negative examples; measure recall/false alerts and location uncertainty.
   Re-import permitted coarse month aggregates for seasonal work, protecting
   sparse cells and avoiding subtraction leaks. Add environmental evidence only
   with provenance/time coverage and validation. Gazebo and physical hardware
   follow measured need, not the app demo.

Acceptance for the full app MVP: authorized workbook → visible density → selected
context → coordinator-chosen small survey/home → reviewed feasible plan → mock
trace → clearly synthetic frame/sighting → human review in the console, without
cloud model credentials or automatic dispatch. The first increment alone does
not complete the sighting part of this chain.

## Simulator and Pi assessment (recommendations)

Start with **ArduPilot SITL using its built-in dynamics**, followed by an optional
Gazebo environment when camera rendering/terrain matters. SITL already runs the
actual autopilot on a computer; Gazebo is an additional external physics/visual
simulator. Neither is installed or validated by this first increment.

Use FastAPI → local worker → MAVLink → SITL, and telemetry/events → normalized
run result → existing console. Real hardware would later use a separate adapter
and deployment; do not enable it through a demo environment flag.

The Pi/autopilot separation in `drone_raspberry_pi_design.md` is sound: the
flight controller owns stabilization and failsafes; the Pi handles camera,
telemetry and buffering. Zero **2** W has a 1-GHz quad-core CPU and 512 MB RAM;
treat backend/laptop inference as the initial design. Onboard detector throughput,
thermal behavior, payload, power and camera synchronization remain unmeasured.
Vehicle GPS is not automatically an animal coordinate: accurate target
geolocation also needs camera calibration, attitude/pose and ground intersection.
Old price/night/thermal-range estimates are proposals, not verified procurement
or performance results. Thermal cameras do not generically see through fog.

FAA requirements and wildlife permissions are separate from an app review.
Part 107 normally requires visual line of sight and applicable airspace
authorizations; autonomous waypoint execution does not grant BVLOS permission.
NOAA advises avoiding drone activity near marine mammals. No generic altitude or
distance constant establishes species/site/activity clearance. Do not propose
approaching/orbiting animals as an authorized experiment on the basis of this
mock. Confirm the intended survey protocol with the rescue network first.

Primary sources checked for this assessment:

- https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html
- https://ardupilot.org/dev/docs/sitl-with-gazebo.html
- https://www.raspberrypi.com/documentation/computers/zero.html
- https://www.faa.gov/air_traffic/publications/aim_html/chap11_section_1.html
- https://www.faa.gov/air_traffic/publications/aim_html/chap11_section_4.html
- https://www.fisheries.noaa.gov/insight/viewing-marine-life

## First increment on `charlotte-drone-historical-context`

Implemented optional historical context on the existing mission contract,
server validation at planning/execution, checksum exposure on the density
response, historical map/cell selection, manual simulation coordinate controls,
and existing mock planning/replay reuse. Selected aggregate context participates
in the existing plan hash, so changed evidence requires a new review. Simulated
flight outputs retain `synthetic: true`; historical evidence remains separately
identified. No schema migration or new runtime dependency is needed.

See `local_drone_demo.md` for installation and the reproducible walkthrough.

## Validation for the first increment

- Focused drone/historical HTTP and planner suite: 19 tests passed. New fixtures
  verify dataset changes, review invalidation, suppressed cells, area containment,
  original planner limits and no incident creation.
- Full offline backend regression suite: 310 passed after installing the existing
  research dependency pandas.
- TypeScript typecheck and Expo web export passed. Ruff passes for all changed
  Python modules; `git diff --check` passes.
- Real supplied NOAA workbook local import: 62,132 rows, 51,942 included, 703
  aggregate cells, of which 217 meet the public threshold. Excluded: 549
  unconfirmed, 9,443 invalid/nondecimal coordinates, 109 outside bounds and 89
  unknown confidence. Coordinate exclusions can bias the map; this change does
  not add DMS parsing or claim geographic completeness.
- HTTP integration using the real import and an explicitly invented small test
  survey completed a reviewed mock run (90 telemetry samples). No raw workbook
  or local database is committed.
- Docker is unavailable in this execution environment. The Docker launch and
  visual browser behavior of this increment have not been verified here; the
  frontend build and backend integration checks do not establish visual QA.
