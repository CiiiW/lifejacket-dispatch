<div align="center">

# LifeJacket

### *Integrating AI-Powered Rescue Coordination and Drone Surveillance for Wildlife Protection*

MS in Applied Data Science Capstone · University of Chicago · 2026

</div>

---

## Table of Contents

1. [🌊 Project Motivation](#1--project-motivation)
2. [🦭 Overview of LifeJacket](#2--overview-of-lifejacket)
3. [🧭 The Project](#3--the-project)
   - [3.1 Public App — a guided report from the person who found the animal](#31-public-app--a-guided-report-from-the-person-who-found-the-animal)
     - [3.1.1 Behind the app: seven stages from photo to report](#311-behind-the-app-seven-stages-from-photo-to-report)
   - [3.2 Rescue Console — where rules score urgency and coordinators decide](#32-rescue-console--where-rules-score-urgency-and-coordinators-decide)
     - [3.2.1 Models perceive, code decides](#321-models-perceive-code-decides)
     - [3.2.2 One case, shared across centers and agencies](#322-one-case-shared-across-centers-and-agencies)
   - [3.3 Drones — a look at places crews can't reach](#33-drones--a-look-at-places-crews-cant-reach)
   - [3.4 Architecture](#34-architecture)
4. [📊 Evaluation and Results](#4--evaluation-and-results)
5. [🌍 Why It Matters Beyond the Animals](#5--why-it-matters-beyond-the-animals)
6. [🚀 Future Work](#6--future-work)
7. [🛠️ Tools Used](#7-️-tools-used)
8. [⚡ Getting Started](#8--getting-started)

---

## 1. 🌊 Project Motivation

*Human activity is driving wildlife toward extinction — and when an injured animal is found, the first few minutes decide what happens next.*

<div align="center">

| | | |
|:---:|:---:|:---:|
| **650,000+** | **49,505** | **1 million** |
| marine mammals killed or seriously injured in fishing gear every year | species threatened with extinction | species could face extinction, many within decades, unless action is taken |
| *Marine Mammal Commission* | *IUCN Red List, July 2026* | *IPBES Global Assessment* |

</div>

<div align="center">
<img src="docs/images/entangled-monk-seal.jpg" width="380" alt="Hawaiian monk seal entangled in derelict fishing net">
<img src="docs/images/oiled-pelicans.jpg" width="380" alt="Brown pelicans coated in oil after the Deepwater Horizon spill">
</div>

<!-- PLACEHOLDER: entangled monk seal — NOAA Fisheries (Permit #10137), public domain -->
<!-- PLACEHOLDER: oiled brown pelicans, Grand Isle LA, 2010 — Int'l Bird Rescue Research Center, CC BY 2.0 (credit required) -->

### Where the current system breaks down

Today a rescue begins with a phone call which starts a chain of events filled with inefficiencies and information + time loss.

**The public doesn't know how to help.** Someone has to find the animal, figure out who to call, and work out how and what to report — usually about a species they can't name and know little about.

**Rescuers triage over the phone.** Coordinators must extract species, condition, location and urgency from a stranger in a few minutes, then dispatch on incomplete information.

**Resources are stretched thin.** Teams are small, and **94% of wildlife rehabilitation programs rely on volunteers** (IWRC, 2026). The whole system is reactive: help waits for a call, and animals in places people don't visit go unseen.

---

## 2. 🦭 Overview of LifeJacket

*LifeJacket looks save animals by improving the efficiency of the current wildlife rescue system. By introducing an AI-powered tools, LifeJacket can increase the quality of care for injured animals.*

<div align="center">
<img src="docs/images/system-overview.png" width="760" alt="LifeJacket system overview: public app, rescue console and drones feeding one structured case">
</div>

<!-- PLACEHOLDER: system overview diagram — adapt slide 5 of LifeJacket_Draft_20261109.pptx -->

**1. The Public App** — An AI chatbot assesses the incident quickly, gives the reporter guidance on what to do in the meantime, and routes the report to the right organization automatically.

**2. The Rescue Console** — Coordinators analyze rather than extract. Every report arrives with weather, tide, daylight, exact location and directions already attached. Humans override anything the AI got wrong, and nothing is dispatched without approval.

**3. Drones** — A quick aerial look at incidents that may not need a crew, so scarce staff go only where they're needed.

> Together, these turn a scattered phone-and-notepad process into one structured case that any coordinator on duty can pick up.

---

## 3. 🧭 The Project

### 3.1 Public App — a guided report from the person who found the animal

<div align="center">
<video src="docs/images/reporter-walkthrough.mp4" width="350" controls></video>
</div>

<!-- PLACEHOLDER: screen recording of the reporter flow, portrait, ~30-45s -->

| | What the reporter does |
|:---:|---|
| **1** | **Photo + map pin.** A photo and an exact location replace the hardest part of the phone call — describing the animal and the place |
| **2** | **Tap the animal you mean.** If several animals are in frame, detection AI outlines each one and the reporter picks the one in trouble |
| **3** | **A few tap-to-choose questions.** The AI asks only what the photo can't show — at most five to identify the species, five to assess condition |
| **4** | **Safety guidance and a trackable case.** Keep your distance, don't handle the animal, and follow the case reference through every status update |

```
Received  →  Accepted  →  En route  →  On scene  →  Animal located  →  Closed
```

<div align="center">
<img src="docs/evidence/reporter_phone_fixture.jpg" width="320" alt="LifeJacket reporter app showing a completed fictional draft">
</div>

*Reporter app UI fixture with a completed fictional draft — no real report, SMS or rescue case.*

> ⚠️ **Honest limit:** the urgency score applies to the animal the reporter selects. If someone taps the healthy seal in a photo that also contains an injured one, the case is scored on the healthy one.

#### 3.1.1 Behind the app: seven stages from photo to report

```
     REPORTER'S PHONE                                  RESCUE CONSOLE
      photo + location                                  report + map
            │                                                 ▲
            ▼                                                 │
  ┌─────────────────────────────────────────────────────────────────┐
  │  1  CONTEXT     tide, weather, daylight, place name   [external] │
  │  2  IDENTIFY    species, up to 5 questions per photo  [AI model] │
  │  3  ASSESS      condition and hazards, up to 5 more   [AI model] │
  │  4  TRIAGE      weighted rules                     ** NO MODEL **│
  │  5  REPORT      the write-up for responders           [AI model] │
  │  6  GUARDRAIL   a second model re-checks it           [AI model] │
  │  7  DISPATCH    rank centers by area + capability  ** NO MODEL **│
  └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                      HUMAN APPROVES
```

The two most consequential stages — **triage** and **dispatch** — are the two with no model in them. That is deliberate, and it is the central design decision of the project.

Context comes from NOAA CO-OPS (tides), Open-Meteo (weather, sunrise and sunset) and Nominatim (place names). The tide matters most: the same animal at the same spot is a different emergency on a rising tide than a falling one.

---

### 3.2 Rescue Console — where rules score urgency and coordinators decide

<div align="center">
<img src="docs/images/console-triage-map.png" width="760" alt="LifeJacket rescue console showing the live triage map with urgency-colored incident pins">
</div>

<!-- PLACEHOLDER: screenshot of the Triage tab at ~1440x820 -->

| Feature | What it does |
|---|---|
| *Live triage map* | Urgency-colored pins; clicking one opens the incident card with photo, summary and the reasons behind its level |
| *Ranked responder candidates* | Distance, capability match and estimated drive time |
| *Contact the reporter* | Call or text for more details or photos, if they opted in |
| *Shift handover* | What changed during a window, and which cases are still open |

> 🧑‍✈️ **HUMAN IN THE LOOP** — Coordinators can override any AI conclusion they judge wrong, and **nothing is dispatched without their approval**.

#### 3.2.1 Models perceive, code decides

AI extracts the evidence. A deterministic, auditable rule set turns that evidence into an urgency level.

| Level | Score |
|---|---|
| *Guidance* | < 1 |
| *Monitor* | 1 to < 3 |
| *Respond* | 3 to < 6.5 |
| *Critical* | 6.5+ **or** a critical override |

**Critical overrides** — entanglement · bleeding wound · breathing distress · unresponsive · immobile cetacean

Weather contributes at most 0.5 points, and a falling tide can shorten the response window.

> Rules keep urgency **explainable** to a coordinator who disagrees, **reproducible** across identical reports, and **tunable** without retraining anything.

*These weights are a prototype and require expert review. They are not clinically validated policy.*

#### 3.2.2 One case, shared across centers and agencies

Strandings don't respect organizational boundaries, so a newer layer lets several rescue centers and a wildlife agency work the same case with controlled visibility.

<div align="center">
<img src="docs/evidence/network_console_fixture.png" width="760" alt="LifeJacket rescue network view as a NOAA reviewer, showing fictional harbor seal and sea lion cases">
</div>

| Role | Sees |
|---|---|
| *Reporter* | Submits a private case and sees only permitted status updates |
| *Center A* | Leads the case and coordinates the response |
| *Center B* | An accepted rescuer confirms response events |
| *NOAA* | A wildlife agency reads the same case across states |

> ✅ **Tested end to end:** 42 automated checks pass for one case across all four roles, on a disposable database.

*Screenshot is a UI fixture with fictional cases and a fictional reviewer.*

---

### 3.3 Drones — a look at places crews can't reach

*Three jobs: verify a case now, watch it over time, patrol next.*

| | **VERIFY · NOW** | **MONITOR · NOW** | **PATROL · NEXT STEP** |
|---|---|---|---|
| *What it answers* | "Is that sea otter pup stranded, or is its mother nearby?" | "Has anything changed since yesterday?" | "Is anything in trouble on a beach nobody walks?" |
| *What starts it* | Low confidence on a reviewed case, or a coordinator's own judgment | A coordinator schedules the next review | A report-density layer on the console map |
| *Built so far* | Case-linked requests, approval and operator handoff, live and recorded frame capture, human review | Due/overdue queue, continue / escalate / finish decisions, background reminders | A historical density layer from NOAA's California records (2006–2025) |

**Nothing flies on a model's say-so.** A suggestion is a prompt for a coordinator, approval is a human action, and every frame that becomes evidence was chosen by a person.

#### A drone request belongs to a case

Drone work used to sit in its own lab page, disconnected from any real report. It now hangs off a reviewed case in the Rescue network and runs one lifecycle:

```
requested  →  approved  →  in progress  →  evidence ready  →  reviewed
                 │              │                                 │
        lead names an     operator confirms site,         answered /
        operator and      weather, range and battery      still uncertain /
        writes the        before anything can be          escalation needed
        question          collected
```

Decline, cancel and failure paths are all kept. **Completing a flight is not the same as answering the question** — the review step is separate, and a person writes the finding.

Findings are an addendum to the case. The original intake and the rescue response status are never overwritten, and the response never waits on a drone.

<div align="center">
<img src="docs/images/drone-request-panel.png" width="760" alt="Case drone requests panel: a verification request with its question, approved operator and attached evidence">
</div>

<!-- PLACEHOLDER: capture from `npm run demo:drone-requests` (loopback :8084, fictional data, no backend) -->

Only the active lead coordinator can change a request; other involved approved staff can read it. Naming an operator records responsibility — it does not grant an account or permission to fly. Every state and evidence change goes through a compare-and-swap revision check and an append-only event log, so two coordinators editing at once cannot silently overwrite each other.

#### When the model isn't sure, it says so — and stops there

The case endpoint now derives a suggestion from confidence values already saved on the case. It makes no model call, issues no aircraft command, and creates no record just by being read.

| Signal | Rule |
|---|---|
| *Animal group uncertain* | Highest probability, pooled across species in the same routing group, falls below the threshold |
| *Condition uncertain* | The saved injury-assessment confidence falls below the threshold |
| *Intake asked for a better photo* | The report explicitly flagged the image as inadequate — at **any** confidence |
| *Species uncertain, group confident* | **No suggestion.** Group is what drives routing, so the exact species can stay open |
| *No usable score* | **No suggestion.** A missing confidence is never invented as a zero |
| *Urgent case* | Review may run **in parallel** — dispatch is never held back for it |

The cutoff is one setting, `DRONE_VERIFICATION_CONFIDENCE_THRESHOLD`, default **0.90** and explicitly provisional.

Acting on a suggestion opens an editable draft. Submitting is a deliberate coordinator action, and the server re-checks the evidence before accepting it. While a request is active, the same evidence will not produce another one; closed, duplicate and unresolved cases produce none at all.

#### From camera to reviewed evidence

Two routes bring footage to a coordinator. Both end in the same place — a person looking at a frame and deciding.

**Live, from the pilot's phone**

```
Mini 2 → DJI Fly  ──RTMP──▶  private receiver  ──▶  sampled preview  ──▶  saved frame
the pilot flies              30-minute grant,       up to 2 fps,          exact frame ID,
manually                     publish-only, cannot   no audio; a feed      immutable, hashed,
                             read any case data     older than 6 s is     case-linked
                                                    marked interrupted
```

MediaMTX v1.21.3 and FFmpeg, bound to loopback by default, with RTMP optionally on a private or VPN interface. The coordinator copies a short-lived publishing address to the operator; the operator flies manually in DJI Fly. Incoming frames sit in a bounded 12-second buffer and selection quotes an exact frame ID, so a newer frame cannot quietly replace the one the coordinator picked. A stale feed is hidden rather than frozen — the coordinator is never shown an old picture as if it were current.

> **No DJI SDK integration, no waypoint flight, no automatic tracking.** Supporting a live stream does not make the aircraft autonomous; that would be a separate decision.

<div align="center">
<img src="docs/images/drone-stream-preview.png" width="760" alt="Coordinator stream panel showing a sampled preview, session state and the save-frame control">
</div>

<!-- PLACEHOLDER: capture from `python scripts/drone_stream_demo.py` — real RTMP receiver, disposable database, generated MP4 -->

**From a recorded file**

The existing extract → hash → review path still stands, and a new selector answers the question that makes long footage usable: *which five frames out of twenty minutes are worth a coordinator's time?*

| Layer | What it does | Cost |
|---|---|---|
| *1 · Scan* | Decode at 160×90 and 2 fps. Drop blurred frames (Laplacian sharpness under half the clip's median), bad exposure and near-duplicates (64-bit perceptual hash); mark shot cuts; cap at 40 candidates | Free, local |
| *2 · Describe* | One model call per surviving candidate, which only describes what the frame shows | One call per candidate |
| *3 · Select* | Deterministic pick of up to 5 clear frames that differ in view and side | Free, code |

**The model never picks the frames.** It describes them; the choosing is code — the same split as everywhere else in LifeJacket. Running `select --scan-only` does layer 1 alone and prints the candidate offsets with no model calls and no cost.

**Advisory screening on a saved frame.** A coordinator can explicitly send one saved frame to the same detection → identification → condition agents that run on reporter photos, then select the intended animal and confirm a second time before assessment. The frame's hash is re-checked first, and the result is stored *beside* the case, never over it. An empty detection means "look again yourself", not "nothing is there".

#### Following through when no one is watching

A monitoring request is only worth making if somebody comes back to it. A separate worker scans the database with no coordinator page open, derives overdue reviews and escalations from the existing workflow, and queues one notification per lead organization.

| | |
|---|---|
| *Transport* | Signed HTTPS webhook — HMAC-SHA256 over the exact body, stable idempotency key |
| *Guarantee* | At least once, not exactly once; five attempts with backoff, redirects rejected |
| *Contents* | Identifiers only — no reporter contact, no GPS, no photos, no free text, no publishing address |
| *Cancellation* | Closing or transferring the case, revoking verification, rescheduling, or acknowledging the attention cancels unsent items |

Delivered means the destination accepted the callback, not that a human read it. No destination is configured in this repository and every flag defaults off.

#### What we actually know about the 90% rule

Two offline studies. Both say the same thing: not yet.

| Study | Result | What it is not |
|---|---|---|
| *Policy sweep* | 12 synthetic scenarios across eight cutoffs. 90% finds all 5 expected positives with 0 unexpected suggestions; 95% and above begin over-suggesting | Not calibrated probabilities, not real observations, and with no held-out split it cannot select a cutoff |
| *Real-photo retrospective* | The same 102 public photos as §4, re-scored with the drone policy's group pooling: **95.1%** agreement (97/102; a tied maximum counts as unresolved). At 90%, 100 photos clear the cutoff and **4 of those disagree with the reference group** | Saved outputs re-analyzed, not a fresh run, not expert-adjudicated, and not aerial |

That second row is the useful one. **A confidence threshold does not catch a confident mistake** — the four disagreements all scored 95% or higher, so no low-confidence trigger would ever have flagged them.

On the 38 assessed condition-pilot photos the rule asks for extra evidence on **24 (63%)**. Whether that is a sensible workload is a question for a response partner, not one we can answer ourselves.

#### How a survey is planned

A coordinator drags a box on the map. The planner turns it into a lawnmower route — rows across the box, alternating direction, starting at the southwest corner. Pure geometry, no model.

<div align="center">
<img src="docs/images/drone-lab-plan.png" width="700" alt="Drone Lab showing a generated lawnmower survey route over the survey area">
</div>

<!-- PLACEHOLDER: screenshot of Drone Lab with a built plan -->

Before anything flies, the plan is validated against hard limits:

| Limit | Value |
|---|---|
| *Altitude band* | 10–100 m |
| *Distance from home* | ≤ 2,000 m |
| *Total route* | ≤ 4,000 m |
| *Simulated wind* | ≤ 8 m/s |
| *Endurance* | 1,200 s with a 25% reserve |
| *Row spacing* | ≤ 50 m |

#### It actually flew — in simulation

<div align="center">

### **1.18 m**
**maximum distance from the planned route, across 280 telemetry samples**

</div>

- ✅ Plan uploaded over MAVLink to **real ArduCopter 4.6.3 autopilot firmware**
- ✅ Flown in software-in-the-loop on GCP, 22 October 2026
- ✅ Completed the survey, returned, landed and disarmed
- ✅ Controlled cancel also landed cleanly; injected link loss was correctly flagged as unconfirmed
- ✅ Normal arming checks throughout — no force-arm, no bypass

<div align="center">
<img src="docs/images/sitl-route-trace.png" width="620" alt="Planned survey route drawn to scale with the 1.18 m deviation band">
</div>

<!-- PLACEHOLDER: planned route vs flown trace plot -->

#### 🔗 The missing link

| Flight | Perception | Coordination |
|---|---|---|
| ✅ Planned route flown in simulation within **1.18 m** | ✅ Recorded video and live RTMP both reach a human reviewer | ✅ Request, approval, evidence and review run end to end on one case |
| ❌ No physical aircraft has flown | ❌ Aerial recognition accuracy is unmeasured | ❌ Never run against real operational data |

**The simulator has no camera, and the camera has never been in the air.** The streaming path proves the software, using a generated test video; the simulation proves the flight worker, using synthetic telemetry. Neither proves that a drone can tell you anything useful about an animal.

The hardware acceptance test is written and waiting. With a Mini 2 and an iPhone, motors off: pair them, publish to the private receiver, measure camera-to-screen delay against a visible clock, then pull the uplink and confirm the coordinator sees *interrupted* rather than a frozen frame. Only after that does aerial footage get evaluated for whether it changes a decision — and that judgment belongs to qualified reviewers, not to us.

---

### 3.4 Architecture

<div align="center">
<img src="docs/images/architecture.png" width="820" alt="LifeJacket architecture: Expo clients, FastAPI backend, Gemini on Vertex AI, SQLite, and external context APIs">
</div>

<!-- PLACEHOLDER: architecture diagram -->

```
clients/reporter_app/        Expo + TypeScript — the public's phone app
clients/responder_console/   Expo + web — the rescue organization's console
clients/shared/              one API client and one design system

backend/lifejacket/
  agents/        six intake agents, a frame observer, a bounded coordination agent
  dispatch/      severity, duplicates, mass strandings, responder matching (no LLM)
  context/       NOAA CO-OPS tides, Open-Meteo weather, Nominatim, OpenRouteService
  access/        role-scoped permissions across centers and agencies
  drones/        planner, SITL adapter, recorded-video pipeline, frame selection
  services/      the intake pipeline — the single best entry point to the code
  models/        30 tables, Pydantic schemas
  api/routes/    15 route groups, 84 endpoints

prompts/         prompts as Markdown, not Python strings
config/          every tunable number, with a comment on where it came from
```

---

## 4. 📊 Evaluation and Results

<a id="evaluation"></a>

### Species identification

102 curated public photos, one initial pass, no follow-up answers.

<div align="center">

| **96%** | **70%** |
|:---:|:---:|
| animal group correct | species correct |
| *98 / 102* | *71 / 102* |

</div>

Animal group is what drives responder matching, so the higher figure is the one that affects routing. Gemini 2.5 Flash, temperature 0.1.

*Exploratory evaluation. Not aerial-detector accuracy, not injury accuracy, and not a calibrated confidence result.*

### Engineering validation

| Result | Detail |
|---|---|
| *Automated tests* | **755**, all running offline against a deterministic stand-in model — no API key, no network, no cost |
| *Simulated flight* | **1.18 m** max deviation across 280 samples on real autopilot firmware |
| *Video pipeline* | **12 frames, 0 failures** on real NOAA footage |
| *Live stream transport* | Real RTMP publish → receive → save-frame → interrupt → reconnect, with MediaMTX and a generated video |
| *Case-linked drone flow* | One case driven through request, approval, evidence and review against the real endpoints |
| *Multi-organization case* | **42 checks** pass for one case across four roles |

### What we have not shown

This matters as much as what we have:

- ❌ **Response-time or survival improvements** — not measured
- ❌ **Injury assessment from the air** — not validated
- ❌ **A calibrated battery model** — an approved simulated flight ran low on reserve in modest wind
- ❌ **A physical flight** — all flight to date is simulated
- ❌ **Real incident data** — the demo database is seeded sample data

> LifeJacket is **not a dispatch system**. No permits are verified and no one is tasked automatically.

---

## 5. 🌍 Why It Matters Beyond the Animals

*Healthy wildlife, healthy ecosystems and healthy people are one system.*

<div align="center">

| **6 in 10** | **3 in 4** |
|:---:|:---:|
| known infectious diseases in people can spread from animals | new or emerging infectious diseases in people come from animals |

*CDC, One Health*

</div>

**Sick wildlife is an early warning system.** California sea lions are among the first animals hit by toxic algae, and eat many of the same kinds of seafood people do — their outbreak data help officials decide when to issue seafood warnings.

**Safer encounters with wild animals.** More than 90% of reported animal rabies cases in the U.S. are in wildlife. The app tells people to keep their distance and not handle the animal.

**Located, structured reports.** Every report carries a photo, coordinates and a condition record, and a deterministic check flags possible mass strandings.

*Earlier warning for public health agencies is an intended benefit, not one we have measured.*

---

## 6. 🚀 Future Work

**From reactive to proactive**

```
TODAY     animal is hurt → someone happens to notice → they find a hotline → a team responds
NEXT      past reports show hotspots → drones patrol → animal spotted early → coordinator opens a case
```

Already built: a historical report-density layer from NOAA's California records (2006–2025) on the console map. *Density reflects where people reported strandings, not risk, so it needs expert validation before it guides patrols.*

**Open work**

- **Pass the hardware acceptance test** — a Mini 2 and an iPhone on the ground, motors off: pairing, private-network reach, measured camera-to-screen delay
- **Close the drone loop** — fly a planned route on a real aircraft so the camera pipeline gets real footage
- **Calibrate the battery model** against real flight data
- **Calibrate the 0.90 suggestion threshold** on reviewer-labeled cases with a genuine held-out split
- **Validate identification** against expert-labeled stranding cases
- **Widen the region** beyond the California pilot bounds
- **Add volunteer matching** — responder ranking currently covers organizations only
- **Field trial** with a partner rescue center

---

## 7. 🛠️ Tools Used

| Layer | Stack |
|---|---|
| *Backend* | Python 3.11+ · FastAPI · SQLAlchemy · SQLite · Pydantic v2 |
| *AI* | Gemini 2.5 Flash via Vertex AI (`google-genai`) — Application Default Credentials only |
| *Clients* | Expo SDK 57 · React Native 0.86 · React 19 · TypeScript |
| *Maps* | MapLibre GL JS (web) · react-native-maps (native) |
| *External data* | NOAA CO-OPS · Open-Meteo · Nominatim · OpenRouteService |
| *Drone* | ArduPilot SITL 4.6.3 · MAVLink · pymavlink · FFmpeg · MediaMTX (RTMP) · Pillow |
| *Identity* | Firebase Authentication |
| *Testing* | pytest (755 offline tests) · ruff |

---

## 8. ⚡ Getting Started

```bash
# Backend
make setup                      # venv + dependencies
make run                        # API on http://localhost:8000
make test                       # 755 tests, fully offline

# Rescue console (web)
cd clients/responder_console && npx expo start --web --port 19006

# Reporter app
cd clients/reporter_app && npx expo start --web --port 19007
```

**No credentials needed for a first look.** From the repository root:

```bash
npm ci && npm run setup:demos && npm run demo:network
```

Open <http://127.0.0.1:8082> — two labeled UI fixtures with fictional data. No GCP login, no SMS, no model calls, no database.

**Walk one case through the drone flow**, from a low-confidence report to a reviewed frame:

```bash
python scripts/run_connected_scenario.py --with-drone
```

It runs the real request, approval, evidence and review endpoints against a temporary database and a generated frame, then writes an HTML trace to `var/connected-drone-workflow/`. No server, no model calls, no aircraft. See [`docs/connected_drone_scenario.md`](docs/connected_drone_scenario.md).

<div align="center">
<img src="docs/evidence/teammate_local_demo.jpg" width="620" alt="LifeJacket local demo landing page">
</div>

See [`docs/teammate_setup.md`](docs/teammate_setup.md) for the full setup, and [`clients/README.md`](clients/README.md) for the two apps.

---

<div align="center">

</div>
