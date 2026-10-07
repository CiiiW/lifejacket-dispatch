# Backend tour

Every file in `backend/`, what it does, and how the pieces fit together.
Written to be read top to bottom once; after that, use the file index.

---

## The two-minute version

A reporter's phone talks to a **FastAPI** server (`api/`). Each request hands
off to **one orchestrator**, `services/pipeline.py`, which asks a **pure
decision function** (`chatbot/session.py`) "what should happen next?" and
then does it:

- call an **LLM agent** (`agents/`) — identify the animal, assess its
  condition, write a report, or check that report;
- run **plain-Python scoring** (`taxonomy.py`, `dispatch/`) on what the agents
  observed — how specific the identification is, how urgent the case is, who
  should respond;
- fetch **real-world context** (`context/`) — tide, weather, place name;
- **save** everything (`models/`).

Two ideas hold it together:

1. **Models observe; Python decides.** The LLMs report *what they see*
   (species probabilities, "there is netting around the neck"). Deterministic
   code turns that into *decisions* (family-level identification, CRITICAL
   severity, which centre to call). Decisions are therefore auditable, stable
   when a prompt changes, and testable without an API key.
2. **One step per request.** A conversation is *state + a decision function*,
   not a loop. The state is saved after every request, so the phone can sleep
   between answers.

---

## How a request flows

```
 phone ──HTTP──▶ api/routes/intake.py          parse request, load state from DB
                        │
                        ▼
                 services/pipeline.py           IntakePipeline.advance()
                        │
          ┌─────────────┼───────────────────────────────┐
          ▼             ▼                               ▼
  chatbot/session.py   agents/*.py ──▶ llm/client.py   context/*.py
  decide_next_step()   one model call   Gemini          tide, weather, geocode
  "ask? run? stop?"         │
                            ▼
                 taxonomy.py, dispatch/*.py      plain-Python decisions
                            │
                            ▼
                 models/repository.py ──▶ SQLite   save incident + state
```

Who may import whom (checked from the real import graph):

| Layer | Packages | Imports from |
|---|---|---|
| HTTP | `api/` | services, models, dispatch |
| Orchestration | `services/`, `chatbot/playground.py` | everything below |
| Decisions & agents | `chatbot/session.py`, `agents/`, `dispatch/`, `context/`, `taxonomy.py` | llm, models, config, geo |
| Foundations | `llm/`, `models/`, `config.py`, `geo.py` | each other only |

Nothing at the bottom imports from the top. That is why `chatbot/session.py`
and `dispatch/severity.py` can be tested in isolation.

---

## One report, request by request

A reporter at Moss Landing photographs a dolphin.

**Request 1 — `POST /intake/start`**
`intake.start_intake` → `IntakePipeline.start_incident` creates an `Incident`
and an empty `ConversationState`. `advance` asks `decide_next_step`, which
says `REQUEST_PHOTO`. The phone opens its camera.

**Request 2 — `POST /intake/{id}/photo`**
The photo is written to disk (`settings.photo_storage_dir`), a `PhotoRow`
records the path. `decide_next_step` → `REQUEST_LOCATION`.

**Request 3 — `POST /intake/{id}/location`**
`IntakePipeline.set_location` calls `context.environment.gather_context`,
which runs **weather, tides, and reverse geocoding in parallel** (~1 s). Then
`advance`:

1. `decide_next_step` → `RUN_IDENTIFICATION` (photo + location present, no
   identification yet).
2. `IdentificationAgent.run` renders `prompts/identification/identify_species.md`
   with the location and tide text, sends it with the photo to Gemini, and
   gets JSON back: common dolphin 0.45, bottlenose 0.38, harbour porpoise 0.12,
   plus a question about beak shape.
3. `taxonomy.resolve_taxon` pools those: no single species reaches 0.90; the
   family Delphinidae holds 0.83; the animal group "cetacean" holds 0.95. So
   the answer so far is *"Whale, dolphin, or porpoise"*.
4. `advance` calls itself: `decide_next_step` → `identification_stop_reason`
   finds no reason to stop (group level is not a stopping rank, a useful
   question exists) → `ASK_CLARIFYING_QUESTION`.

The phone shows *"Does it have a long, distinct beak, or a short rounded
face?"* with three buttons. State is saved, including
`pending_agent = "identification"`.

**Request 4 — `POST /intake/{id}/reply` with "long beak"**
`ConversationState.add_reporter_message` records the answer and sets
`identification_stale = True`. `decide_next_step` therefore → 
`RUN_IDENTIFICATION` again. This time Gemini rules out the porpoise
(common 0.50, bottlenose 0.44) and says `species_distinguishable: false` —
beak length and colouring can't be judged from 50 yards.

`resolve_taxon` → **family Delphinidae, "Oceanic dolphins", 0.94**.
`identification_stop_reason` → stop: *"No question can separate the remaining
candidates from a safe distance; settling at family level."*

`decide_next_step` → `RUN_ASSESSMENT`. `AssessmentAgent.run` gets the
identification (including both species probabilities), the tide (falling), and
the transcript. It reports the animal immobile and asks whether it is
breathing.

**Request 5 — reply "yes"**
`assessment_stale = True` → assessment re-runs → confident: alive, immobile,
on its side. Then, in plain Python, `dispatch.severity.score_severity`:
cetacean + immobile triggers the `cetacean_mobility` **hard rule** →
**CRITICAL**. `decide_next_step` → `FINALISE`:

1. `ReportAgent` writes the responder report — *"Oceanic dolphin (common 0.50,
   bottlenose 0.44); confirm on arrival."*
2. `GuardrailAgent` checks it for invented claims and unsafe advice.
3. `dispatch.duplicates.find_duplicate` looks for the same animal reported
   nearby in the last 24 h.
4. `dispatch.matching.rank_centers` ranks rescue centres by county coverage
   and capability.

Status becomes `awaiting_dispatch`. A coordinator approves a responder in the
console (`POST /responders/assign`); nothing is dispatched automatically.

---

## File by file

### Top level of `lifejacket/`

**`config.py`** — Every setting, in one place. Secrets and deployment values
come from environment variables / `.env` (`Settings`, via pydantic-settings);
modelling decisions come from `config/scoring.json` (`load_scoring_config`).
Kept separate because the team argues about and version-controls the weights,
but each developer has their own credentials. Nothing else reads `os.environ`.

**`geo.py`** — Pure maths, no I/O. `haversine_km` (distance between two
points), `estimate_drive_minutes` (straight-line × 1.3 at 55 km/h — a rough
ETA), `bounding_box` (a cheap SQL pre-filter before exact distance checks).

**`taxonomy.py`** — Turns per-species probabilities into an answer.
`resolve_taxon` walks species → genus → family → animal group and returns the
**finest rank whose pooled probability reaches the threshold**, keeping the
individual species as `members`. `normalise_candidates` repairs model output
first (fills a missing genus from the scientific name; rescales probabilities
that sum past 1). `describe_resolution` renders the one-line summary that goes
into later prompts and the report.

### `models/` — the data layer

**`schemas.py`** — The vocabulary of the whole system, as Pydantic models.
*Read this first.* Enums (`IncidentStatus`, `AnimalGroup`, `TaxonRank`,
`SeverityLevel`, …), agent outputs (`IdentificationResult`,
`TaxonResolution`, `AssessmentResult`, `IncidentReport`), context
(`EnvironmentalContext`, `TideConditions`, `WeatherConditions`), and the
aggregate `Incident`. Pydantic validates the LLMs' JSON at the boundary, so a
confidence of 1.7 fails here rather than corrupting a score downstream.
`IdentificationResult` has convenience properties — `display_name`,
`confidence`, `animal_group`, `is_confident` — that everything downstream uses
instead of digging through candidates.

**`tables.py`** — SQLAlchemy tables: `incidents`, `photos`, `chat_messages`,
`responders`, `assignments`, `incident_logs`. The design compromise: fields the
app filters or maps on (location, severity, taxon rank) are real columns; the
full nested agent output is stored alongside as JSON. See
[`data_model.md`](data_model.md).

**`db.py`** — Creates the engine (SQLite by default; change `DATABASE_URL` for
Postgres). `session_scope` for scripts, `get_session` for FastAPI. `init_db`
creates tables but never alters them — delete `lifejacket.db` after a schema
change.

**`repository.py`** — The only code that converts between Pydantic models and
database rows. `save_incident` recomputes the promoted columns from the nested
objects on every save, so they cannot drift. Also serialises
`ConversationState` (`save_conversation_state` / `load_conversation_state`) and
runs the two location queries: open incidents near a point (for the map) and
recent nearby incidents (for duplicate detection).

### `llm/` — the model boundary

**`client.py`** — `LLMClient`, the single place a model is called. Uses the
Google Gen AI SDK on Vertex AI with **JSON mode** — the model is constrained to
return JSON matching a schema, rather than asked politely and parsed with brace
slicing. Retries with exponential backoff, and records latency and token counts
for cost tracking. Auth is Application Default Credentials; no API key.

When every retry fails it raises `LLMError`, in one of two flavours so the
failure can be diagnosed: `LLMCallError` (the call itself failed: network,
quota, auth) or `LLMResponseError` (the model replied with something unusable).
Both carry `.attempts`. Catch `LLMError` unless you care which.

Caps `thinking_config.thinking_budget` (`settings.llm_thinking_budget`,
default 1280). Gemini 2.5 Flash spends part of `max_output_tokens` on internal
reasoning before writing the JSON reply, and that length varies call to call
-- uncapped, a long thinking pass can truncate the JSON mid-string, which
surfaces as `json.JSONDecodeError: Unterminated string` (or `Expecting
value`) on every retry, not as an obviously flaky model. `max_output_tokens`
(default 6144) is set well above the thinking budget so there is always real
room left for the answer -- measured live across all four agents' prompts,
thinking stayed at 700-950 tokens and combined thinking+output never passed
1429; see the comment above `llm_thinking_budget` in `config.py` for the full
measurement. A higher ceiling costs nothing: Vertex AI bills by tokens
actually produced, not by the cap.

**`schema.py`** — Builders for those JSON schemas (`object_schema`, `enum_of`,
`UNIT_INTERVAL`, …). Convention: **every field is required**, so the model must
say `false` rather than silently omit an awkward flag.

**`prompts.py`** — Loads prompt templates from `prompts/*.md` and fills their
`{placeholders}`. `system_principles()` is the safety text sent with every
call. `clear_prompt_cache()` makes prompt edits take effect in a notebook.

**`fake.py`** — `ScriptedLLMClient`, an offline stand-in with the same
`generate_json` method. Works out which agent is calling from its schema and
replies from a queue. Ships four scenarios — `sea_lion`, `seal`, `dolphin` (one
per way identification can stop) and `raccoon` (a non-marine animal, proving
identification/triage are not marine-only even though dispatch currently is).
Used by the tests and by the notebooks' offline mode. Records every prompt it
receives (`client.calls`). Queue an exception instead of a reply to simulate
the model being down for one call (`test_health.py` does this throughout).

### `agents/` — the four model calls

Every agent is ~30 lines of configuration on top of `base.py`: a prompt file, a
schema, a result type, and `build_prompt_values` mapping Python objects into
the prompt's placeholders.

**`base.py`** — `Agent.run`: render prompt → call model (with system
principles) → validate JSON into the result type. Keeps `last_prompt` and
`last_response` for debugging in notebooks.

**`identification.py`** — Agent 1. Photo + location + conversation in;
per-species candidates (with genus and family), one question, and a
`species_distinguishable` judgement out. **It does not decide how confident it
is overall** — `parse` hands the candidates to `taxonomy.resolve_taxon`.
Prompt: `prompts/identification/identify_species.md`.

**`assessment.py`** — Agent 2. Identification + tide/weather + conversation
in; ten condition flags (wound, bleeding, entanglement, …), surroundings
(people, dogs, surf), reporter instructions, and possibly a question out.
**It does not assign severity.** `_group_notes` injects biology that changes
the advice completely: a seal resting on a beach is normal; a dolphin out of
the water is always an emergency; a "dead-looking" sea turtle may be
cold-stunned. Prompt: `prompts/assessment/assess_situation.md`.

**`report.py`** — Agent 3. Writes the responder-facing report: a headline that
stands alone in a push notification, a short summary, ordered actions,
equipment, hazards, and explicit unknowns. Prompt:
`prompts/report/write_report.md`.

**`guardrail.py`** — Agent 4. A separate model call checks the report against
the source data for *ungrounded claims* and *unsafe advice*. A failed report is
**held for human review**, never dropped — a false positive must not bury an
emergency. Prompt: `prompts/report/guardrail_review.md`.

### `chatbot/` — conversation flow

**`session.py`** — The heart of the chatbot, and no I/O at all.
`ConversationState` is plain, serialisable data: stage, transcript, question
counts, probed features, pending question, and the `*_stale` flags.
`decide_next_step(state)` returns the next action. `identification_stop_reason`
is the stopping rule, in order:

1. confident at a stopping rank (species or genus by default);
2. 5 questions used;
3. agent says no question can separate the species (→ genus/family answer);
4. agent repeats a feature it already asked about.

The `*_stale` flags make sure an agent re-runs after the reporter answers it.

**`playground.py`** — `ChatPlayground`, for talking to the chatbots from
Jupyter. Wraps the real pipeline with no database, and can stop before a step:
`identification_only`, `identification_and_assessment` (real identification,
then real assessment, stops before the report), `assessment_only` (skips
identification -- you assume a species), and `full`. Prints each turn with
the reason it was chosen; `show_*`, `last_prompt`, `check_report` for
inspection. Used by notebook 3, which chains `identification_only` ->
`assessment_only` manually across its three parts, saving each stage's
result to plain variables the next stage reads -- so `identification_and_assessment`
is there for scripts/tests that want the two stages in one call instead.

### `context/` — the world around the animal

**`weather.py`** — Open-Meteo (free, global, keyless): temperature, wind,
gusts, rain chance, visibility, sunset. `weather_risk_score` rates how hard
conditions make the rescue *for responders* (thresholds in `scoring.json`).
Returns `None` on failure — never invents weather.

**`tides.py`** — NOAA CO-OPS (free, keyless, US coasts). Finds the nearest of
~3,000 tide stations (within 75 km), fetches high/low predictions, and works
out whether the tide is **rising or falling** — the most decisive single fact
for a stranded marine mammal. Adds wave height and sea temperature from
Open-Meteo Marine. `describe_tide` writes the sentence the agents read.

**`geocode.py`** — OpenStreetMap Nominatim: coordinates → place name and
**county**. County is the join key to the rescue-centre directory. The state is
deliberately excluded from match terms (every California entry contains
"California", which made distant centres look local).

**`environment.py`** — `gather_context` runs the three lookups concurrently
and records any that failed in `unavailable`. `summarise_for_prompt` renders it
all as the text block the agents see.

### `dispatch/` — deterministic decisions

**`severity.py`** — Turns assessment flags into a triage level. Hard rules
first (entanglement, bleeding wound, breathing trouble, unresponsive, immobile
cetacean → CRITICAL), then a weighted sum, then a capped weather adjustment,
then a tide adjustment, then thresholds. Guard: weather alone can never cause
CRITICAL. Returns the itemised contributions and reasons so the console can
show its working. `recommended_action` maps a level to policy, including
`volunteer_allowed`.

**`matching.py`** — Ranks the 33 centres in `data/rescue_centers.csv`. Score =
0.58 × area match (county overlap) + 0.42 × capability (species permit, live vs
dead response, entanglement gear, rehab, transport). Penalises sending a
carcass-only team to a live animal. Every candidate carries a written
rationale, because coordinators approve reasons, not numbers. Refuses to match
`TERRESTRIAL` or `DOMESTIC_ANIMAL` at all -- this directory is marine-only, and
an area-only match (a county overlap with zero capability score) would
otherwise surface a seal centre for a reported coyote.

**`duplicates.py`** — Is this the same animal someone already reported?
Weighted distance (0.45), time (0.35), and species agreement (0.20), inside a
hard 1 km / 24 h window. Duplicates are linked, never deleted. Only an
incident someone is actively handling can be matched against, and reports that
disagree on the animal group are flagged for the coordinator rather than
cancelled (`is_probable_duplicate` / `is_possible_duplicate`).

**`mass_stranding.py`** — Is this one animal or several? Adds up
`animal_count` across the incidents open now: the largest count within one
incident and its duplicates, summed across separate incidents nearby. Two or
more cetaceans is flagged. Computed per request by the incident routes, never
stored. See `docs/data_model.md`.

**`species.py`** — Maps free-text names ("Guadalupe fur seal") to an animal
group. Not on the live path; used to compare responders' typed species with the
agent's answer in notebook 2.

### `services/`

**`pipeline.py`** — `IntakePipeline`, the orchestrator. `advance()` asks
`decide_next_step` what to do and does it; agent steps re-enter `advance` so
"run the model" and "ask its question" happen in one request. `_run_assessment`
is where severity is computed; `_finalise` writes the report, runs the
guardrail, checks duplicates, and ranks responders. Accepts `session=None` (in
memory), `client=` (swap the model), and `stop_at=` (halt before a step).

A failed model call never escapes `advance()` as an exception. Every agent is
called through `_call_agent`, which records the outcome and lets the step pick
its fail-safe: identification and assessment ask the reporter to try again
(`StepAction.SERVICE_RETRY`, nothing lost); a failed report still sends the
incident to coordinators without one; a failed guardrail check holds the
report. All three end in "a human looks at it", never in a lost report.

**`health.py`** — The per-incident health record: model calls, retries,
failures (which agent, which kind), fail-safes used, and whether the reporter
is waiting to retry. Stored in `incident.metrics["health"]`, returned by
`GET /incidents/{id}` as `health`, and logged as one summary line when intake
finishes (WARNING if anything went wrong). `needs_review()` is what makes an
unrecovered failure show up as "held for coordinator review" on the console;
a retry that succeeded is recorded but does not hold anything.

### `api/`

**`main.py`** — Creates the FastAPI app, CORS, routers, and creates tables at
startup. Run with `uvicorn lifejacket.api.main:app --reload --app-dir backend`;
interactive docs at `/docs`.

**`routes/intake.py`** — The reporter's endpoints: `start`, `photo`,
`location`, `reply`, `retry`, and `GET` to resume. Each loads state, calls the
pipeline, saves, and returns one `TurnResponse` shape — so the phone has a
single rendering path. `retry` re-runs a step that failed on a model error
(`service_error: true` on the turn) without adding to the conversation.

**`routes/incidents.py`** — The responder console: the map feed (small
payloads), full incident detail (report, species probabilities, transcript,
guardrail findings, pipeline `health`), status changes, and the closing
**log** — the only ground truth the project ever gets.

**`routes/responders.py`** — The directory, seeding it from the CSV, live
responder positions, volunteer duty toggle, coordinator **assign**, accept /
decline, and ETAs for the reporter's map.

### `tests/`

| File | Covers |
|---|---|
| `test_severity.py` | Triage: hard rules, weights, weather guard, tide, confidence. The clearest spec of triage behaviour |
| `test_taxonomy.py` | Pooling: species → genus → family → group, rescaling, descriptions |
| `test_session.py` | Stopping rules, question budget, stale-rerun, retakes |
| `test_dispatch.py` | Distance, duplicate scoring, centre ranking, species grouping |
| `test_duplicates.py` | Which incidents a report may be cancelled against, and when it is flagged instead. Database and HTTP |
| `test_mass_stranding.py` | The counting rule, the animal count reaching the report and guardrail prompts, and events forming and ending over HTTP |
| `test_prompts.py` | Every prompt renders with its agent's real values; safety rules still present |
| `test_pipeline.py` | Whole conversations in memory with the scripted model |
| `test_api.py` | A whole conversation over HTTP with a real (temporary) database |
| `test_health.py` | Model failures: error types, each step's fail-safe, the retry endpoint, and the health record surviving save and reload |

---

## Questions teammates will ask

**Why isn't severity just an LLM output?**
Because a coordinator must see *why* a case is critical, the rule must not
shift when someone edits a prompt, and we need to test it without an API key.
The model observes; Python decides.

**Why does the system, not the model, choose species vs. family?**
Same reason. The model gives honest probabilities; `taxonomy.py` applies one
rule to every incident. "Report the finest rank that reaches 0.90" is easy to
explain, test, and tune.

**Why might it ask zero questions?**
If the photo already settles the species (or genus) at 0.90+, asking would only
delay a rescue. Questions exist to resolve uncertainty, not to fill a form.

**Why stop at "oceanic dolphins" instead of guessing?**
Routing depends on the animal group, which is certain. A confident wrong
species is worse than an honest family with both probabilities, and the
responder confirms the species on the beach.

**What happens with a photo of a whale?**
Works today, no change needed -- whales are `AnimalGroup.CETACEAN` ("whales,
dolphins, porpoises"), same as a dolphin. That group already has dispatch
terms, severity rules, and group-specific advice.

**What about a raccoon, or someone's dog?**
Also identified correctly (`TERRESTRIAL`, `DOMESTIC_ANIMAL`), with real
group-specific advice and a real severity score -- identification and triage
are not marine-only. Dispatch is, though: `data/rescue_centers.csv` is a
marine-mammal-only directory, so these two groups get an honestly empty
responder list rather than a misleadingly wrong one. See the `raccoon`
scenario in `llm/fake.py`.

**Where are the prompts?** `prompts/`, as Markdown. Edit, then
`clear_prompt_cache()` in a notebook or restart the server.

**How do I try it without GCP access?** Notebook 3, `MODE = "offline"`.

**How do I change the threshold or allow family-level stops?**
`.env`: `IDENTIFICATION_CONFIDENCE_THRESHOLD`, `CONFIDENT_TAXON_RANKS`.

**What is least trustworthy right now?**
The new identification prompt has only been run against scripted replies, the
0.90 threshold is unvalidated, and the injury flags have never been evaluated
against labelled photos. See the README's *Known limitations*.
