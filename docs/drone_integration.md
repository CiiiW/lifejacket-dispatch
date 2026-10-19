# Drone Integration (Proposal)

Status: imagery and physical-flight proposal; the local simulation slice is implemented.

Current scope: the local synthetic planner and mock replay are now implemented;
see [drone architecture](drone_architecture.md) and
[teammate setup](local_drone_demo.md). The imagery and physical-flight designs
below remain proposals.

## Why

The team's intake pipeline currently runs identification and assessment off
a single bystander photo. The README names two known gaps that follow
directly from that: species identification accuracy is ~54%, and injury
flags have never been evaluated against labelled data. A drone sent to the
reported coordinates can supply a second, better-controlled visual source
without changing how the rest of the pipeline works.

This also answers the brief the professor gave the team: make the project
more AI/autonomy-forward, not just logistics. The dispatch decision below is
written as a deterministic autopilot analog to `dispatch/severity.py`, the
same pattern the backend already uses to keep a reviewable boundary between
what a model observes and what a function decides.

## Three integration points

### 1. Multi-angle visual input for identification and assessment

A drone launched to the incident's GPS coordinates orbits the animal and
records a short video. Frames are sampled and handed to the existing
identification and assessment agents the same way a reporter's photo is
today — this adds a source, it does not change `agents/identification.py`
or `agents/assessment.py` internally. More angles and closer range than a
bystander's phone shot is a legitimate accuracy lever against both
known gaps above.

Where this lands: a new `context/drone.py` module (same tier as the
existing `context/` weather/tide/geocoding providers), producing a list of
frames plus capture metadata that feeds into `services/pipeline.py` as an
additional `PhotoRow`-like input.

### 2. Deterministic drone dispatch decision (the autopilot piece)

Whether a drone flies at all is a decision, not a model call — the same
split the backend already draws for severity. A new `dispatch/drone_dispatch.py`
takes distance from the nearest drone base, wind/weather limits, time of
day, and airspace/no-fly data, and returns a bounded flight plan (fly to
point, loiter at a fixed altitude, record, return) or a reason the flight
was not viable. No model chooses the flight path.

This mirrors `dispatch/severity.py`'s "the model decides what it observes,
a function decides what that means" split, and keeps the same property:
a coordinator can see *why* a flight was or was not launched.

### 3. Proactive scouting / patrol

Separate from any single incident: scheduled patrol flights over
high-traffic coastline to catch strandings before a public report comes in,
or to get a head count during a mass stranding (feeds
`dispatch/mass_stranding.py`'s existing scale logic). This is the most
speculative of the three and depends on having a drone base and flight
authorization in a given area — treat it as a stretch goal, not required
for the proposal to stand on its own.

## Safety boundary (non-negotiable)

Real mission constraints must come from current site/species/activity rules
and the relevant operator's authorizations. A single generic MMPA distance or
altitude constant is not an established drone flight policy. NOAA advises
avoiding drone activity near marine mammals and says national UAS guidance is
under development; see [its primary guidance](https://www.fisheries.noaa.gov/insight/viewing-marine-life).
The implemented local prototype accepts only simulation requests and supplied
synthetic exclusions. Real execution and wildlife clearance are future work.

This also extends the backend's existing human-in-the-loop boundary
(`responders/assign` requires a human; nothing dispatches automatically).
A drone flight is a dispatch action, so it should require the same
coordinator approval before launch, not run as a background automation.

## Suggested new modules

| You want to... | Add |
| --- | --- |
| Decide if/how a drone flies for an incident | `backend/lifejacket/dispatch/drone_dispatch.py` |
| Fetch drone video/frames for an incident | `backend/lifejacket/context/drone.py` |
| Enforce the MMPA approach-distance floor | constant + check inside `drone_dispatch.py`, unit-tested the way `test_severity.py` tests the hard rules |
| Feed drone frames into identification | extend the `PhotoRow`-shaped input `services/pipeline.py` passes to `agents/identification.py` |
| Require coordinator approval before flight | new endpoint alongside `POST /responders/assign`, same approval pattern |
| Scheduled patrol flights | out of scope for v1; revisit once single-incident dispatch works |

## Open questions

| Question | Why it matters |
| --- | --- |
| Where does drone base/availability data live? | `dispatch/matching.py` already struggles with missing coordinates for rescue centers (`data/rescue_centers.csv` has no lat/long); drone bases need real coordinates from day one |
| Who owns flight authorization / airspace rules for the demo area? | Needed before `drone_dispatch.py` can produce a real "viable" decision instead of a placeholder |
| Live hardware or simulated flights for the demo? | Affects whether `context/drone.py` needs a real drone SDK integration or a scripted stand-in, same pattern as `llm/fake.py` for Gemini in tests |
