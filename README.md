# LifeJacket Dispatch

Agentic AI dispatch for stranded and injured wild animals.

Someone finds an animal on a beach and photographs it. LifeJacket identifies
the species by asking a few questions, works out what should happen using the
tide and weather at that spot, and sends a concise incident report to the
nearest rescue organisation permitted to respond.

---

## How it works

```
                    REPORTER'S PHONE                      RESCUE ORGANISATION
                 (clients/reporter_app)              (clients/responder_console)
                           |                                      ^
                    photo + location                              | report + map
                           v                                      |
  ┌────────────────────────────────────────────────────────────────┴──────────┐
  │                   PYTHON BACKEND  (backend/lifejacket)                    │
  │                                                                           │
  │  1. CONTEXT        tide, weather, place name          context/            │
  │                    NOAA CO-OPS + Open-Meteo + Nominatim                   │
  │                                                                           │
  │  2. IDENTIFY       own questions per photo, max 5     agents/             │
  │                    species, or genus/family + probs   identification.py   │
  │                                                                           │
  │  3. ASSESS         condition + hazards, max 5 more    agents/             │
  │                    wound? entangled? can it move?     assessment.py       │
  │                                                                           │
  │  4. TRIAGE         severity level  ← NOT an LLM call  dispatch/           │
  │                    deterministic, weighted, audited   severity.py         │
  │                                                                           │
  │  5. REPORT         the responder-facing write-up      agents/report.py    │
  │                                                                           │
  │  6. GUARDRAIL      second model checks it for         agents/             │
  │                    invented claims + unsafe advice    guardrail.py        │
  │                                                                           │
  │  7. DISPATCH       rank organisations by area +       dispatch/           │
  │                    capability, for human approval     matching.py         │
  └───────────────────────────────────────────────────────────────────────────┘
```

Read [`backend/lifejacket/services/pipeline.py`](backend/lifejacket/services/pipeline.py)
for this flow as actual code. It is the single best entry point to the codebase.

---

## Repository layout

```
lifejacket-dispatch/
├── backend/                  ← all the logic lives here (Python)
│   ├── lifejacket/
│   │   ├── agents/           LLM agents: identify, assess, report, guardrail
│   │   ├── chatbot/          when to ask / when to stop + notebook playground
│   │   ├── context/          weather, tides, reverse geocoding
│   │   ├── dispatch/         severity, duplicates, mass strandings, responder matching (no LLM)
│   │   ├── llm/              the one place we call a model
│   │   ├── models/           schemas, database tables, repository
│   │   ├── services/         pipeline.py — the end-to-end workflow; health.py
│   │   ├── api/              FastAPI routes (thin: no business logic)
│   │   ├── config.py         every setting, in one file
│   │   ├── taxonomy.py       pools species probabilities into genus/family
│   │   └── geo.py            haversine, ETA, bounding boxes
│   ├── tests/                203 tests, no API key needed
│   └── requirements.txt
│
├── clients/
│   ├── reporter_app/         Expo RN — the public's phone app
│   ├── responder_console/    Expo RN + web — rescue organisations
│   └── shared/api.ts         one API client, shared by both
│
├── prompts/                  ← prompts as Markdown, not Python strings
│   ├── system_principles.md  safety rules sent with EVERY model call
│   ├── identification/
│   ├── assessment/
│   ├── report/
│   └── legacy/               the prototype's 29-prompt library, for reference
│
├── config/scoring.json       severity weights, dispatch weights, species groups
├── data/
│   ├── rescue_centers.csv    33 real West Coast stranding network centres
│   ├── schema/               the prototype's 45-column CSV contract (reference)
│   └── seeds/                example incident rows
│
├── notebooks/                walkthrough, evaluation, and a chatbot playground
├── research/
│   └── dispatch_benchmark/   directory vs. online search (built, never run)
├── archive/prototypes/       the previous ChatBox / agent2 notebooks
└── docs/                     backend_tour.md — every backend file explained
```

### Where to make a change

| You want to… | Edit |
|---|---|
| Change what the agent asks the reporter | [`prompts/identification/identify_species.md`](prompts/identification/identify_species.md) |
| Change when the agent stops asking | [`backend/lifejacket/chatbot/session.py`](backend/lifejacket/chatbot/session.py) → `identification_stop_reason` |
| Allow stopping at family level, or move the 0.90 threshold | `CONFIDENT_TAXON_RANKS`, `IDENTIFICATION_CONFIDENCE_THRESHOLD` in `.env` |
| Change how species pool into genus/family | [`backend/lifejacket/taxonomy.py`](backend/lifejacket/taxonomy.py) |
| Re-tune triage urgency | [`config/scoring.json`](config/scoring.json) |
| Change what counts as a mass stranding | `mass_stranding` in [`config/scoring.json`](config/scoring.json); the rule is in [`backend/lifejacket/dispatch/mass_stranding.py`](backend/lifejacket/dispatch/mass_stranding.py) |
| Change how responders are ranked | [`backend/lifejacket/dispatch/matching.py`](backend/lifejacket/dispatch/matching.py) |
| Add a weather or tide signal | [`backend/lifejacket/context/`](backend/lifejacket/context/) |
| Add an endpoint | [`backend/lifejacket/api/routes/`](backend/lifejacket/api/routes/) |
| Add a safety rule | [`prompts/system_principles.md`](prompts/system_principles.md) |
| Change what happens when a model call fails | `_call_agent` and the fail-safes in [`backend/lifejacket/services/pipeline.py`](backend/lifejacket/services/pipeline.py); what gets recorded in [`services/health.py`](backend/lifejacket/services/health.py) |

---

## Running it

Requires **Python 3.11+**. (Google stopped shipping Vertex AI updates for 3.10
after 2026-10-04, and the code uses `match` statements.)

```bash
# 1. Dependencies
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. Credentials for the LLM agents (steps 2, 3, 5, 6 above).
#    No API key — this uses Application Default Credentials.
gcloud auth application-default login

# 3. Optional config. Every value has a working default.
cp .env.example .env

# 4. Run
uvicorn lifejacket.api.main:app --reload --app-dir backend
```

Then open <http://localhost:8000/docs> for interactive API docs — the quickest
way to drive the whole intake flow without writing a client.

```bash
# Load the 33 real rescue centres into the database
curl -X POST localhost:8000/responders/seed

# Start a report
curl -X POST localhost:8000/intake/start -H 'Content-Type: application/json' -d '{}'
```

### Tests

```bash
pytest                 # 203 tests, no API key or network required
```

The deterministic logic — severity, duplicates, matching, taxonomy, the
conversation state machine — is pure functions, so it is tested properly. Whole
conversations are tested too, in memory (`test_pipeline.py`) and over HTTP
(`test_api.py`), using a scripted stand-in for Gemini. Start with
[`backend/tests/test_severity.py`](backend/tests/test_severity.py): it is the
clearest specification of how triage actually behaves.

### Notebooks

```bash
jupyter lab notebooks/
```

| Notebook | What it is for |
|---|---|
| [`01_pipeline_walkthrough`](notebooks/01_pipeline_walkthrough.ipynb) | Tour of the decision logic against live tide and weather data |
| [`02_agent_evaluation`](notebooks/02_agent_evaluation.ipynb) | Compare agent answers against what responders found |
| [`03_try_the_chatbots`](notebooks/03_try_the_chatbots.ipynb) | **Talk to** all three chatbots in one photo: identification, assessment, report + guardrail. Each stage saves its result to plain variables the next stage reads -- no retyping a species name between stages |

Notebook 3 has an **offline mode** (default) that needs no credentials: a
scripted stand-in replaces Gemini while every other line of real code runs.
Switch `MODE = "live"` and add a photo to `notebooks/sample_photos/` to talk to
the real model.

```python
id_chat = ChatPlayground.identification_only(photos=["seal.jpg"], latitude=36.80, longitude=-121.79)
id_chat.answer("shorter than a person")
id_chat.show_identification()
print(id_chat.last_prompt("identification"))   # exactly what the model was sent
```

### Clients

See [`clients/README.md`](clients/README.md).

---

## Design decisions worth knowing

These are the choices that will surprise you if you did not make them.

### 1. Severity is deterministic, not an LLM call

The model decides what it **observes** (is there a wound, is the animal
entangled). [`dispatch/severity.py`](backend/lifejacket/dispatch/severity.py)
decides what those observations **mean**, using weights from
[`config/scoring.json`](config/scoring.json).

This split exists because a coordinator has to be able to see *why* something
was triaged critical. "The model said so" is not reviewable, cannot be tested
without an API key, and shifts silently every time someone edits a prompt.

The prototype had the opposite problem: an LLM prompt assigned severity 0–3
while a parallel deterministic path computed a different number from the same
flags — and the prompt was explicitly instructed to ignore weather, which the
current specification requires.

### 2. Questions are chosen per photo, and "dolphin" can be a final answer

There is no questionnaire. Once a photo and location arrive, the
identification agent asks about whatever would most change its own
probabilities for *this* photo — a sharp photo of a sea lion may need no
questions at all. It asks at most 5.

The agent reports per-species probabilities with genus and family;
[`taxonomy.py`](backend/lifejacket/taxonomy.py) pools them up the tree and the
system settles on the **finest rank that reaches 0.90**. Identification stops
when it is confident at species or genus level, when 5 questions are used, or
when the agent says no question could separate the remaining species from a
safe distance. That last case is how common vs bottlenose dolphin in a distant
photo becomes *"oceanic dolphins, 0.94 (common 0.50, bottlenose 0.44)"* — both
probabilities travel with the report.

Note common and bottlenose dolphins are different **genera**, so "dolphin" is a
**family**-level answer. Family is not an early-stop rank by default: harbor
and elephant seals pool to 0.90 as "true seals", but one question about size
usually settles which, so the agent asks it. Add `"family"` to
`CONFIDENT_TAXON_RANKS` to stop sooner.

The rank is chosen in Python, not by the model, so the rule is identical on
every incident and unit-tested.

### 3. Some conditions bypass the score entirely

Entanglement scores 1.4 additively, below the 3.0 "respond" threshold. So an
entangled animal with no other symptoms would be triaged "monitor" while the
line tightens around it as it moves. **Hard rules** force critical for
entanglement, bleeding wounds, respiratory distress, unresponsiveness, and any
cetacean that cannot move.

Conversely, weather can **never** be the sole cause of a critical rating. It
adds at most 0.5 points, and there is an explicit demotion guard if the
animal's own condition does not independently reach the threshold.

### 4. The tide is the most important input

For a stranded marine mammal it usually matters more than anything else:

- A **rising** tide may refloat the animal with no intervention. Patience is
  often the right recommendation, and a rushed rescue can do more harm.
- A **falling** tide is a hard deadline. The animal is left further from the
  water every minute, and a heat-stress clock starts.
- An immobile **cetacean** on a rising tide may drown, because it cannot lift
  its blowhole clear.

The prototype had no tide data at all, so it could not distinguish these. This
was the biggest single gap.

### 5. Failed lookups say so

Every external call can fail, and a rescue cannot wait for NOAA. Failures are
recorded by name in `EnvironmentalContext.unavailable` and surfaced in the
report as explicit unknowns.

This replaced a `PlaceholderWeatherProvider` in the prototype that fabricated
plausible-looking numbers from arithmetic on the coordinates — and was the
default, so demos showed invented weather that looked real.

### 6. Prompts are Markdown files

Not Python strings. A prompt change becomes a readable diff in code review,
non-programmers on the team can edit them, and
[`backend/tests/test_prompts.py`](backend/tests/test_prompts.py) checks every
one still renders with the values its agent actually supplies.

### 7. A second model checks the report before anyone sees it

[`agents/guardrail.py`](backend/lifejacket/agents/guardrail.py) reviews the
generated report against the source data for two failure modes: claims nothing
supports, and advice that would hurt someone. The dangerous advice here is
specific and recurring — pushing a stranded cetacean back to sea, pouring water
into a blowhole, moving an apparently-orphaned seal pup, the public washing an
oiled bird.

A failed report is **held for a human, not discarded**: a guardrail false
positive must not bury a real emergency.

This pattern is carried over from the prototype, where it was the strongest
idea in the codebase.

### 8. Nothing dispatches automatically

Every deployment is approved by a human coordinator
(`POST /responders/assign`). Stranding networks operate under permits, and the
system must never place an untrained person next to a protected animal without
someone having agreed to it. At `respond` severity and above,
`volunteer_allowed` is false — a safety boundary, not a preference.

### 9. County, not state, routes an incident

Rescue centres describe coverage by county ("Del Norte and Humboldt Counties,
California"), so reverse geocoding resolves the county and matches on that.

Including the state in the match terms was a real bug found while building
this: every entry in the California directory contains the word "California",
so a centre 400 km away in Del Norte County scored as highly for a Monterey
incident as the centre covering Monterey itself.

---

## Known limitations

Be honest about these in any write-up.

| Limitation | Detail |
|---|---|
| **Species accuracy is ~54%** | Best prompt strategy, from the team's vision research. Animal-*group* accuracy is much better, and group is what routes the incident. The research notebook itself (`research/vision_confidence/`) was removed from this repo for disk space -- this number is what remains of it. |
| **Never run against the real model** | The new dynamic-question prompt and taxonomy pooling are tested end to end only with scripted replies. How often Gemini asks good questions, splits look-alikes honestly, and correctly flags species as indistinguishable is unmeasured. Notebook 3 in live mode is the place to start. |
| **The 0.90 confidence threshold is unvalidated** | 50 of 485 answers at 90%+ confidence were wrong in the research data. Every stop decision is logged so this can be calibrated. See notebook 2. |
| **Vision research used 5 photos** | One was a dog control. Treat the strategy comparison as indicative only. |
| **Injury flags have never been evaluated** | And they feed severity scoring. This is the highest-value gap. |
| **No authentication** | `RESPONDER_ID` is hardcoded in the console. Must be fixed before more than one person uses it. |
| **Tides are US-only** | NOAA CO-OPS covers US coasts. Weather and geocoding are global. |
| **Rescue centres have no coordinates** | `data/rescue_centers.csv` has no latitude/longitude or street address, so organisation distance and ETA are always null. Area matching (by county) works fine; only distance is affected. |
| **Dispatch only has data for marine animals** | Identification and assessment work for any animal (`AnimalGroup.TERRESTRIAL`, `DOMESTIC_ANIMAL`, `OTHER_MARINE` are real, supported groups — see the `raccoon` scenario in `llm/fake.py`). But `data/rescue_centers.csv` is a *West Coast Marine Mammal Stranding Network* directory, so a coyote or pet dog correctly gets no suggested responder rather than a misleading one. Adding a wildlife-rehab directory needs no change to identification or triage, only a second data file and a merge in `dispatch/matching.py`. |
| **No real ETAs** | `estimate_drive_minutes` is straight-line distance × 1.3. Google Directions is wired for navigation but not for ETAs. |
| **Dispatch benchmark never ran** | [`research/dispatch_benchmark/`](research/dispatch_benchmark/) was built with both run switches set to `False`. Its conclusion is open. |
| **Clients are scaffolds** | Screens and API wiring are real; styling is minimal; no offline support, push notifications, or photo EXIF extraction yet. |

---

## Where to pick up

Roughly in priority order:

1. **Evaluate the injury flags** against a labelled photo set. They drive
   triage and have never been measured. The 400-image set used for the
   team's earlier vision research is no longer in this repo (`research/vision_confidence/`
   was removed for disk space, metadata included) -- this needs a fresh
   labelled set, or the original iNaturalist observations re-identified.
2. **Calibrate the 0.90 stop threshold** using notebook 2 once there are closed
   incidents with responder logs.
3. **Authentication** for the responder console, so actions are attributable.
4. **Photo EXIF extraction** — `PhotoRow` has the columns, nothing populates
   them. EXIF often has a better location than a hand-typed one, plus a capture
   time that tells you how stale the sighting is.
5. **Geocode the rescue centres** so distance and ETA work. The directory has
   no addresses, so this likely means resolving each organisation by name once
   and committing the coordinates alongside the CSV.
6. **Real ETAs** via the Google Directions API.
7. **Push notifications** so a report reaches an on-call responder without them
   watching the map.
8. **Run the dispatch benchmark** and settle whether online search beats the
   directory.

---

## Data notes

- **Rescue centre contacts** come from the public 2026 West Coast Marine Mammal
  Stranding Network directory.
- **Raw photos are not in this repo** (about 1.1 GB, gitignored). They were
  originally downloaded from public iNaturalist observations by scraping
  cells that lived in `research/vision_confidence/`; that folder (notebook,
  result CSVs, and the observation-ID metadata needed to re-fetch the
  photos) was removed for disk space, so rebuilding the set now means
  re-scraping iNaturalist from scratch rather than replaying a saved
  metadata list. iNaturalist content is licensed by its observers — check
  each observation before reusing images.
- **Reporter photos** are written to `PHOTO_STORAGE_DIR` (gitignored), not the
  database. A stranding location can be personally identifying, so images stay
  deletable independently of the record.
- **Dispatch benchmark cases are synthetic.**

## Prior work

The previous prototype lives in [`archive/prototypes/`](archive/prototypes/)
and nothing active reads from it. Its genuinely valuable parts were carried
forward: the scoring weights (now `config/scoring.json`, previously hardcoded
and unread), the rescue centre directory, the prototype's intake questions (now asked
dynamically, only when the photo leaves them open), the
guardrail pattern, and the 45-column CSV contract (kept in
[`data/schema/`](data/schema/) for reference).

See [`PROJECT_NOTES.md`](PROJECT_NOTES.md) for the decision log.
