# LifeJacket Project Notes

Running log of structure, decisions, known issues, and open work. Newest
entries at the top of each section.

For the repository tour and design rationale, see [README.md](README.md).

## Current Layout

| Folder | What it is |
|---|---|
| `backend/lifejacket/` | All application logic. Python. See the README's layout table |
| `backend/tests/` | 120 tests. No API key or network needed |
| `clients/reporter_app/` | The public's phone app. Expo + React Native |
| `clients/responder_console/` | Rescue organisation app. Expo + RN, phone **and** web |
| `clients/shared/api.ts` | One API client, shared by both apps |
| `prompts/` | Prompts as Markdown. `system_principles.md` ships with every call |
| `config/scoring.json` | Severity weights, dispatch weights, species groups |
| `data/` | Rescue centre directory, the legacy CSV schema, seed rows |
| `notebooks/` | 1. pipeline walkthrough 2. agent evaluation harness 3. talk to all three chatbots in sequence |
| `research/dispatch_benchmark/` | Directory vs. online search. Built, never run |
| `archive/prototypes/` | The previous ChatBox / agent2 notebooks. Nothing reads from here |
| `docs/data_model.md` | Entities, lifecycle, and the promoted-column compromise |
| `docs/backend_tour.md` | Every backend file explained, and one report traced request by request |

## Decisions

- **2026-10-01** Fixed a real bug: identification could settle on a guess at
  0.30 confidence having asked 0 of its 5 questions, because
  `identification_stop_reason` (chatbot/session.py) accepted the agent's
  "no question can separate these candidates" at face value regardless of how
  low that confidence actually was -- correct for a genuine close-look-alike
  pool (e.g. common vs. bottlenose dolphin at 0.89 combined) but wrong for a
  three-way 0.30/0.30/0.30 split across unrelated families, where more
  information would clearly help even without a single question that cleanly
  separates exactly two leading candidates. Added
  `identification_min_confidence_to_settle` (0.80, config.py): below it, the
  agent may not stop just by claiming no question helps -- it falls back to a
  short list of generic clues (size, behaviour, colouring, limb/fin shape) not
  yet asked about, and only settles once those are exhausted too or the
  5-question budget runs out. Also loosened the prompt's "when to stop"
  section to spell out the difference between a genuine pooled look-alike
  case and a thin, unrelated spread. Added `TestLowConfidenceMustKeepAsking`
  in test_session.py; full suite (124 tests) and lint pass.
- **2026-10-01** `research/vision_confidence/` (the team's vision-strategy
  research: notebook, result CSVs, charts, and the iNaturalist observation
  metadata) was deleted from the working tree for disk space. It was briefly
  restored from git's index by mistake (the files were staged but not yet
  committed, so `git checkout` brought them back); re-deleted and unstaged
  once clarified -- this was intentional, not data loss to fix. The headline
  numbers it produced (~54% top-1 accuracy, 50/485 wrong at 90%+ confidence,
  5-photo sample) are kept in README.md and PROJECT_NOTES.md prose since
  those facts do not depend on the notebook being present. Rebuilding the
  photo set now means re-scraping iNaturalist from scratch -- the metadata
  that would have let it replay is gone too.
- **2026-10-01** Merged notebooks 03/04/05 into one (`03_try_the_chatbots.ipynb`).
  The three-notebook split meant continuing from identification into
  assessment required reading notebook 03's printed species and retyping it
  as literal arguments in notebook 04's cell -- exactly the kind of manual
  copy a notebook should not require. The merged notebook runs identification
  (Part 1), saves `SPECIES`/`SCIENTIFIC_NAME`/`FAMILY`/`ANIMAL_GROUP`/
  `CONFIDENCE` to plain variables, feeds those into assessment (Part 2), then
  continues the same `assess_chat` object into the report and guardrail
  (Part 3) -- no object is rebuilt from scratch between Part 2 and Part 3, and
  no value is ever hand-typed between Part 1 and Part 2. To test a different
  species mid-run, edit the four variables in place and re-run from there.
  Added `ChatPlayground.identification_and_assessment` (real identification
  then real assessment, stopping before the report) to `playground.py` for
  callers that want both stages in one call; the notebook itself chains
  `identification_only` -> `assessment_only` across its three parts instead,
  specifically so the species hand-off is visible as named variables rather
  than hidden inside one call.
- **2026-10-01** Follow-up on the truncation fix below: the truncation
  recurred after it had apparently been fixed. Root cause this time was two
  things, not the budget: (1) `llm_model` had been changed to
  `gemini-3.5-flash`, which 404s under `GCP_LOCATION=us-central1` (it only
  resolves under `location="global"` in this project) -- reverted to
  `gemini-2.5-flash`; (2) the notebook kernel was very likely still holding
  pre-fix settings, since Jupyter does not reload `config.py` on its own --
  restarting the kernel is required after any config change. Separately,
  tightened all four prompts' connective prose and added explicit length caps
  on free-text/list output fields (no rule, example, or safety content cut --
  `test_prompts.py`'s safety-keyword check still passes), then re-measured
  live: 24 calls across all four schemas, worst combined thinking+output was
  1429 tokens, all well under budget. Raised `LLM_THINKING_BUDGET` to 1280 and
  `LLM_MAX_OUTPUT_TOKENS` to 6144 for real margin over that measurement (a
  higher ceiling costs nothing -- billing is by tokens produced, not the cap).
  Verified with 5 full real multi-turn conversations end to end, 0 failures.
- **2026-10-01** Fixed a real live-mode bug: assessment calls on a real photo
  were failing all 3 retries with `JSONDecodeError: Unterminated string` (or
  `Expecting value`), at a different character offset each time. Root cause:
  gemini-2.5-flash spends part of `max_output_tokens` on internal "thinking"
  before writing the JSON reply, and thinking length is not deterministic --
  uncapped, it could eat most of the 2048-token budget and truncate the JSON
  mid-string. Added `LLM_THINKING_BUDGET` (default 1024) and raised
  `LLM_MAX_OUTPUT_TOKENS` to 4096. Reproduced against the real model with the
  failing photo and confirmed 3/3 clean runs after the fix.
- **2026-10-01** `AnimalGroup` now classifies any non-human animal, not just
  the five marine groups. Added `DOMESTIC_ANIMAL` (pets/livestock) and
  broadened `TERRESTRIAL` to mean any wild land animal, not only "false
  report of a dog". `OTHER_MARINE` already existed in the enum but was a
  dead end (no group notes, no dispatch terms) -- it now has both. The
  identification prompt explicitly instructs the model to classify every
  photo, not only the ones that turn out to be a marine mammal.
  `dispatch/matching.py` now refuses to match `TERRESTRIAL` or
  `DOMESTIC_ANIMAL` against the rescue directory at all (previously a
  county-only area match could still surface a seal centre for a reported
  coyote, which is actively misleading) -- an empty dispatch list is the
  honest answer until a wildlife-rehab directory exists. See the `raccoon`
  scenario in `llm/fake.py` for an end-to-end demonstration.
- **2026-10-01** Removed the five scripted intake questions. Every question
  now comes from the identification or assessment agent and is chosen for the
  photo in front of it. Max 5 per agent.
- **2026-10-01** Identification may answer at genus or family level. The
  agent gives per-species probabilities with genus and family; `taxonomy.py`
  pools them and the system takes the finest rank reaching 0.90. Early stop
  at species or genus; family accepted once the agent says no question can
  separate the species (e.g. common vs bottlenose dolphin), or the budget runs
  out. Per-species probabilities are kept and shown in the report and console.
  Configurable via `CONFIDENT_TAXON_RANKS`.
- **2026-10-01** Renamed `SPECIES_CONFIDENCE_THRESHOLD` to
  `IDENTIFICATION_CONFIDENCE_THRESHOLD`, since it now applies to the resolved
  taxon at any rank.
- **2026-10-01** Severity is computed in deterministic Python
  (`dispatch/severity.py`) from weights in `config/scoring.json`, **not** by an
  LLM. The agents report observations; scoring interprets them. Reason: a
  coordinator must be able to see which flags fired and what each contributed,
  and triage must not shift silently when a prompt is edited.
- **2026-10-01** Hard rules force CRITICAL regardless of the additive score,
  for entanglement, bleeding wounds, respiratory distress, unresponsiveness,
  and immobile cetaceans. Entanglement scores only 1.4 additively and would
  otherwise be triaged "monitor".
- **2026-10-01** Weather can never be the sole cause of CRITICAL. Capped at
  +0.5 with an explicit demotion guard.
- **2026-10-01** Tide data added (NOAA CO-OPS) — the biggest gap in the
  prototype, which had none. Rising vs. falling tide changes the
  recommendation completely.
- **2026-10-01** Dropped the placeholder weather provider. Failed lookups are
  now recorded in `EnvironmentalContext.unavailable` and surfaced as explicit
  unknowns. The old provider fabricated plausible numbers from arithmetic on
  the coordinates, and was the default.
- **2026-10-01** Reverse geocoding (Nominatim) replaces the hardcoded
  50-entry place-to-county map. Routing matches on **county**, not state:
  every California directory entry contains "California", so matching on it
  gave a centre 400 km away the same score as the local one.
- **2026-10-01** Unified on the `google-genai` SDK with real JSON mode and
  retries. The prototype ran two SDKs on two Gemini versions, had no retry
  logic anywhere, and parsed JSON by brace-slicing prose.
- **2026-10-01** Prompts live in `prompts/*.md`, not Python strings, so a
  prompt change is a reviewable diff and non-programmers can edit them.
- **2026-10-01** `config/scoring.json` is now load-bearing. It was previously
  dead — every weight was hardcoded in the notebooks and nothing read the file.
- **2026-10-01** Storage moved from the append-only CSV to SQLAlchemy +
  SQLite. Swaps to Postgres by changing one connection string.
- **2026-10-01** Kept the prototype's guardrail/grounding gate. A failed check
  **holds** the report for a human rather than discarding it, so a false
  positive cannot bury a real emergency.
- **2026-10-01** Rewrote `.gitignore`. It previously ignored `/*` and
  allow-listed individual folders (a holdover from the repo root doubling as a
  JupyterLab home directory), which silently excluded every new top-level
  folder.
- **2026-09-28** Code, notebooks, prompts, CSV results and charts go to GitHub;
  raw photos stay out of the repo.
- **2026-09-28** Kept the CDRL prompt strategy in the CV module: highest top-1
  accuracy (53.9%) and lowest confidence when wrong (35.8). Differences are
  small and based on only 5 photos. *Note: nobody on the team has recorded
  what "CDRL" stands for — it is not expanded anywhere in the repo.*
- **2026-09-28** Rescue centre contacts come from the public 2026 West Coast
  Marine Mammal Stranding Network directory.

## Change Log

### 2026-10-01 — Identification and triage work for any animal

- **New** `AnimalGroup.DOMESTIC_ANIMAL`; broadened `TERRESTRIAL` to mean any
  wild land animal. Gave `OTHER_MARINE` (already in the enum, previously
  unused) real group notes and dispatch terms.
- **`identify_species.md`** now explicitly tells the model to classify every
  photo, not only marine mammals.
- **Correctness fix in `dispatch/matching.py`**: `rank_centers` previously
  could surface a seal centre for a reported coyote, because area-only
  scoring does not need a capability match to produce a nonzero score.
  `TERRESTRIAL` and `DOMESTIC_ANIMAL` are now refused outright, returning an
  honest empty list instead.
- **New** `raccoon` scenario in `llm/fake.py` demonstrating the full path:
  confident species ID, real severity score, real group-specific advice, zero
  dispatch candidates. 120 tests.
- Documented in the README's *Known limitations*: identification and triage
  now cover any animal; the rescue directory still covers marine animals
  only, so non-marine reports correctly get no suggested responder.

### 2026-10-01 — Dynamic questions and chatbot notebooks

- **Removed** `chatbot/questions.py` and the scripted intake step.
- **New** `taxonomy.py`: pools species probabilities into genus/family/group.
- **New** `chatbot/playground.py` and notebooks 03–05 to talk to each chatbot
  from Jupyter, plus `llm/fake.py` (scripted offline model, 3 scenarios).
- **Pipeline** can run without a database and stop before a chosen step.
- **Fixed a bug present since the restructure**: reporter answers were
  recorded but the agent that asked was never re-run, so identification stayed
  at its first guess no matter what the reporter said (and an entanglement
  answer never reached triage). Added `*_stale` flags to the conversation
  state, plus `test_pipeline.py` and `test_api.py`, which drive whole
  conversations in memory and over HTTP.
- **Removed** `choose_primary_species` and `is_unknown_term`: they reconciled the
  prototype's separate vision and chatbot species guesses, which no longer
  exist as two outputs. 110 tests.

### 2026-10-01 — Full restructure

Rebuilt the repository around a Python backend with two thin clients. The
previous notebook-based pipeline is in `archive/prototypes/`.

- **New**: `backend/lifejacket/` with `agents/`, `chatbot/`, `context/`,
  `dispatch/`, `llm/`, `models/`, `services/`, `api/`. 102 tests.
- **New**: tide, weather, and reverse-geocoding integrations, run concurrently
  (~1 s total rather than the sum).
- **New**: resumable conversation state machine replacing the notebook's
  `while True: input()` loop. State serialises to the database, so a reporter
  can close the app mid-intake.
- **New**: feature-based question dedup. The prototype compared question
  strings exactly, which any rephrasing defeated — and each repeat cost one of
  only five questions.
- **New**: Expo clients for reporter and responder, the console building for
  web as well as phone.
- **New**: `notebooks/`, `docs/data_model.md`, `Makefile`, `.env.example`.
- **Carried forward**: scoring weights, the 33-centre directory, the five
  scripted intake questions, the guardrail pattern, the 45-column CSV contract
  (reference only).
- **Fixed on port**: the assessment prompt line that appeared three times, two
  of them run together on one line.

### 2026-09-28

- Put the project under git, connected to
  https://github.com/CiiiW/lifejacket-dispatch.
- Reorganized files; old ChatBox versions and round-1 testing moved to
  `archive/`.
- V8 gained a Save To Incident Database section and 10 injury/distress flags.

## Known Issues

- **The dynamic-question prompt has not been run against real Gemini.** All
  end-to-end testing used scripted replies; no GCP credentials were available
  while it was built.
- **Species accuracy is about 54%.** Animal-*group* accuracy is considerably
  better, and group is what routes an incident, so the operational impact is
  smaller than the headline number.
- **The 0.90 confidence stop threshold is unvalidated.** 50 of 485 answers at
  90%+ confidence were wrong in the research data. Every stop decision is now
  logged with its reason so this can be calibrated. See notebook 2.
- **Vision research used 5 photos**, one a dog control. All strategies missed
  the same two, both within the correct animal group.
- **Injury and distress flags have never been evaluated**, and they feed
  severity scoring. Highest-value gap in the project.
- **No authentication.** `RESPONDER_ID` is hardcoded in the console, so
  responder actions are not attributable.
- **Tides are US-only** (NOAA CO-OPS). Weather and geocoding are global.
- **The rescue centre directory has no coordinates or addresses**, so
  organisation distance and ETA are always null. County-based area matching is
  unaffected.
- **ETAs are straight-line distance × 1.3**, not real routing.
- **No migrations.** `create_all` ignores changed columns on existing tables;
  delete the local database after a schema change.
- **Photo EXIF is not extracted.** `PhotoRow` has the columns, nothing fills
  them.
- **Dispatch benchmark never ran.** Both run switches in the notebook are
  `False` and no results were committed, so its conclusion is open.
- **Nominatim rate limit.** One request per second, and its policy requires a
  real contact in `HTTP_USER_AGENT`. Results are cached, but a batch
  evaluation run needs throttling.
- **This repo sits in an iCloud-synced Desktop folder.** Git operations are
  slow, and files can be evicted to placeholders that read as empty until
  touched. Do not create a virtualenv inside the repo — 19,000 files makes
  `git status` take minutes and syncs 334 MB to iCloud.

## Open Work (in suggested order)

1. Evaluate the injury flags against a labelled photo set. The 400-image set
   from the earlier vision research is gone (`research/vision_confidence/`
   removed for disk space, 2026-10-01) -- needs a fresh labelled set.
2. Calibrate the 0.90 stop threshold once closed incidents with responder logs
   exist (notebook 2 has the harness).
3. Authentication for the responder console.
4. Photo EXIF extraction — often a better location than a typed one, plus a
   capture time showing how stale the sighting is.
5. Real ETAs via the Google Directions API.
6. Push notifications, so a report reaches an on-call responder without them
   watching the map.
7. Run the dispatch benchmark and settle directory vs. online search.
8. Re-run the vision strategy comparison on more than 5 photos.
9. Measure the guardrail false-positive rate. If coordinators see warnings on
   reports they then approve unchanged, they will stop reading them.
