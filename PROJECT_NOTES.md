# LifeJacket Project Notes

Running log of structure, decisions, known issues, and open work. Newest
entries at the top of each section.

For the repository tour and design rationale, see [README.md](README.md).

## Current Layout

| Folder | What it is |
|---|---|
| `backend/lifejacket/` | All application logic. Python. See the README's layout table |
| `backend/tests/` | 203 tests. No API key or network needed |
| `clients/reporter_app/` | The public's phone app. Expo + React Native |
| `clients/responder_console/` | Rescue organisation app. Expo + RN, phone **and** web |
| `clients/shared/api.ts` | One API client, shared by both apps |
| `clients/shared/theme.ts` | One design system (navy/seafoam), shared by both apps |
| `scripts/seed_demo_incidents.py` | `make demo`: real incidents from `demo/` photos + CSV |
| `demo/` | Demo photos and `incidents.csv`. See its README |
| `prompts/` | Prompts as Markdown. `system_principles.md` ships with every call |
| `config/scoring.json` | Severity weights, dispatch weights, species groups |
| `data/` | Rescue centre directory, the legacy CSV schema, seed rows |
| `notebooks/` | 1. pipeline walkthrough 2. agent evaluation harness 3. talk to all three chatbots in sequence |
| `research/dispatch_benchmark/` | Directory vs. online search. Built, never run |
| `archive/prototypes/` | The previous ChatBox / agent2 notebooks. Nothing reads from here |
| `docs/data_model.md` | Entities, lifecycle, and the promoted-column compromise |
| `docs/backend_tour.md` | Every backend file explained, and one report traced request by request |

## Decisions

- **2026-10-05** Mass strandings are detected by counting, and the count is
  derived on every request instead of stored. A new report changes the answer
  for incidents filed earlier (the second reporter is often the one who sees
  the other animals), so anything written at intake time would be stale by
  the time a coordinator opened it. Counting rule: the largest `animal_count`
  within one incident and its duplicates (same animals, several photos),
  summed across separate incidents within 2 km and 24 h (the system already
  judged those to be different animals). Cetaceans only, following NOAA's
  definition, because several pinnipeds on one beach is normal. It is a flag
  for the coordinator and changes neither severity nor dispatch ranking: a
  stranded cetacean is already critical, and how many teams to send is a
  human decision.
- **2026-10-05** A duplicate may only cancel a report in the narrow case it
  was built for: the same animal, reported again, while someone is already
  handling it. Two rules follow. (1) Only an incident in an active status
  (`awaiting_dispatch` through `on_scene`) can be a duplicate target. Before,
  any incident within 1 km and 24 h counted, including resolved cases and
  intakes nobody finished, so a re-stranded animal or a report made next to an
  abandoned one was cancelled with no responder offered. (2) Reports that
  disagree on the animal group are never cancelled. Distance and time alone
  could clear the 0.70 threshold, so a dolphin 200 m from a seal an hour later
  was cancelled as the seal. Those are now dispatched normally and flagged for
  the coordinator as a possible duplicate. **This changes an earlier intent**:
  the scorer treats a group mismatch as "a partial penalty, not a veto",
  because reporters describe the same animal inconsistently. The score still
  works that way. What changed is that the score alone no longer withholds a
  response; the cost of the new rule is an occasional second look by a
  coordinator, and the cost of the old one was an animal nobody was sent to.
- **2026-10-05** A failed model call must never lose a report. After
  `LLMClient`'s retries are exhausted, each pipeline step now has a fail-safe
  instead of raising (which was a 500 for the reporter and nothing recorded):
  identification/assessment ask the reporter to try again with nothing lost; a
  failed report writer still sends the incident to coordinators, without the
  prose, held for review; a failed guardrail check holds the report (this one
  already existed). Every outcome ends with a human seeing the incident.
- **2026-10-05** Pipeline health is recorded per incident, in
  `incident.metrics["health"]` (`services/health.py`), not in a separate
  table or service. It needs no migration, travels with the incident to the
  console, and is the per-incident data any later trend monitoring would be
  built from. Only *unrecovered* failures hold an incident for review; a retry
  that succeeded is recorded and shown as a quiet note, because holding every
  retried incident would train coordinators to ignore the banner.
- **2026-10-03** Upgraded both clients from Expo SDK 52 to 57 (React Native
  0.86, React 19.2, TypeScript 6). Forced rather than chosen: Expo Go only
  ever supports the current SDK, so on an iPhone there was no way to run the
  reporter app at all -- and a custom dev build needs either Xcode (not
  installed here) or a paid Apple Developer account. `npx expo install --fix`
  could not resolve incrementally; what worked was writing the SDK 57
  versions into both `package.json` files and reinstalling from scratch.
  Two fallout fixes: TypeScript 6 rejects MapLibre's side-effect CSS import
  without a `declare module '*.css'`, and `make run` now binds `0.0.0.0`
  because uvicorn's default `127.0.0.1` is unreachable from a phone.
  Verified after upgrading: console renders with map, markers, and photos;
  reporter app's iOS bundle builds; both typecheck.
- **2026-10-03** The console can finally show the reporter's photo. It could
  not before: the agents read the image bytes off the upload request, so
  nothing ever read them back, and neither `IncidentDetail` nor any endpoint
  exposed them. Added `photos` to the incident detail (beside the species and
  severity derived *from* those photos, so evidence and conclusion arrive in
  one response), `photo_url` to the map feed for list thumbnails, and
  `GET /incidents/{id}/photos/{photo_id}` to serve the bytes. Bytes still
  live on disk, not in the database -- the reason in `PhotoRow`'s docstring
  still holds: a stranding photo can identify the reporter and must stay
  independently deletable. The endpoint is unauthenticated like everything
  else here, which is fine on localhost and is not fine deployed.
- **2026-10-03** Web map is MapLibre GL (`TriageMap.web.tsx`), replacing the
  placeholder. Tiles from MapTiler/Stadia when a key is set, keyless OSM
  raster otherwise, with a badge saying which. Routes come from
  OpenRouteService *through the backend* (`GET /incidents/{id}/route`) so the
  routing key is never in the web bundle; with no key it returns a straight
  line flagged `source: "straight_line"` and the map dashes it, because a
  straight line must never read as a drive time. Native stays on
  `react-native-maps`: MapLibre's RN binding needs a custom dev client and
  would break Expo Go. `maplibre-gl` is pinned to v4 -- v6 uses
  `import.meta`, which Metro cannot bundle -- and `babel.config.js` exists
  only to enable the static-class-block transform MapLibre needs.
- **2026-10-03** Rescue centres had no coordinates at all, so there was
  nothing to plot: the 2026 directory lists coverage as prose ("Del Norte and
  Humboldt Counties, California") and no addresses. `POST /responders/geocode`
  forward-geocodes that prose through Nominatim, peeling it back to the first
  county plus state when the whole string fails. 29 of 33 resolve. These are
  **service-area centroids, not addresses** -- fine for seeing which stretch
  of coast a centre covers, wrong for navigating to. Replace with real
  addresses before anyone relies on the pins.
- **2026-10-02** Added `scripts/seed_demo_incidents.py` (`make demo`) to build
  demo incidents from `demo/` -- photos plus a CSV of coordinates, a
  `condition` sentence, and the true species. It drives the real intake API
  rather than inserting rows, so the demo shows real reports; the alternative
  (writing incident rows directly) would have meant hand-faking report text,
  which is the one thing a demo must not do. The CSV's `species` column is
  ground truth, not an override -- the agent still identifies from the photo,
  and the script prints an agent-vs-truth table. Two incidents get closed with
  a responder log entry so the demo has both open and resolved states. The
  script refuses to run if two rows are within the 1 km duplicate radius,
  because the backend would mark the later ones `cancelled` and silently drop
  them from the console (this happened while seeding by hand).
- **2026-10-02** `GET /incidents` grew an `include_closed` flag, and the
  console's triage panel a "Show closed" toggle. Logging an outcome resolves
  an incident, and the list only ever returned open ones -- so closing an
  incident made it vanish with no way to see it again. Cancelled duplicates
  stay hidden either way: those are noise, not history.
- **2026-10-02** Gave both clients a shared design system
  (`clients/shared/theme.ts`): navy `#0B132B` ground, seafoam `#48CAE4`
  accent, glass cards at 12px radius, one type scale. Screens import tokens
  instead of hardcoding hex, and `severityColour` was re-tuned because the
  old white-background values went muddy on navy. Also replaced the
  console's three-state view switch with a tab bar (Triage / Incident / Log
  outcome): previously the only route to the detail and log screens was
  clicking a list row, so with an empty incident list two of the three
  screens were unreachable.
- **2026-10-02** Three things were blocking the clients from running at all,
  all now fixed: (1) no `metro.config.js`, so Metro could not resolve
  `clients/shared/*` from either app (the re-export in `src/lib/api.ts` did
  not help -- it reaches outside the app directory too, which is the thing
  Metro refuses); (2) `expo-asset` was missing from both apps'
  dependencies; (3) `expo/tsconfig.base` sets `moduleResolution: node10`,
  which current TypeScript errors on -- both tsconfigs now override it with
  `bundler`. Node itself was not installed on this machine; `brew install
  node` tries to build LLVM from source here (Homebrew reports the setup as
  Tier 3), so install Node from nodejs.org or via nvm instead.
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

### 2026-10-05 — Mass stranding detection

- **`models/schemas.py`**: `AssessmentResult.animal_count` (default 1) and
  `MassStranding`.
- **Assessment agent and prompt**: record `animal_count`; healthy animals
  nearby do not count; with several, flags describe the worst-off one; for a
  cetacean, "are others stranded nearby" is listed as a question worth asking.
- **Report and guardrail agents and prompts**: both are given the count. The
  guardrail used to treat any stated number of animals as invented; it now
  checks the number against the count.
- **New `dispatch/mass_stranding.py`** and `mass_stranding` in
  `config/scoring.json` (groups, minimum animals, distance, time).
- **`models/repository.py`**: `find_stranding_reports`.
- **API**: `animal_count` and `mass_stranding` on `GET /incidents/{id}`;
  `in_mass_stranding` on each row of `GET /incidents`.
- **Console**: "Possible mass stranding" banner on the incident, naming the
  other incidents in the event; MASS STRANDING tag in the list.
- **New `tests/test_mass_stranding.py`** (38 tests). 203 tests total.

### 2026-10-05 — Duplicate reports can no longer cancel the wrong incident

- **`dispatch/duplicates.py`**: `ACTIVE_DUPLICATE_TARGET_STATUSES`;
  `is_probable_duplicate` also requires the animal groups not to disagree;
  new `is_possible_duplicate` (score at the threshold, groups disagree);
  `find_duplicate` prefers a match that can be linked over a closer one that
  cannot.
- **`models/repository.py`**: `find_duplicate_candidates` filters on status.
- **API**: `possible_duplicate` on `GET /incidents/{id}`.
- **Console**: the linked case now reads "Linked as a duplicate of ..."; the
  new "Possible duplicate of ..." line is for the flagged, still-dispatched
  case. (The old text said "Possible duplicate" about incidents that had
  already been cancelled.)
- **New `tests/test_duplicates.py`** (17 tests) and 5 more in
  `test_dispatch.py`. 165 tests total.

### 2026-10-05 — Model-failure handling and per-incident health

Ports PR #3 (built against the archived prototype) onto the backend. Retries
and the guardrail fail-safe already existed here; this adds what was missing.

- **`llm/client.py`**: `LLMError` now has two subclasses, `LLMCallError`
  (call failed) and `LLMResponseError` (unusable reply), and carries
  `.attempts`. Existing `except LLMError` code is unaffected.
- **`agents/base.py`**: `AgentError` carries `.agent`, `.kind`, `.attempts`;
  attempts are recorded in metrics even when the call fails.
- **New `services/health.py`**: the per-incident health record.
- **`services/pipeline.py`**: every agent runs through `_call_agent`;
  fail-safes for identification, assessment, and report (see Decisions). The
  guardrail agent's latency and tokens are now recorded too (they were not).
  `GuardrailVerdict.check_failed` separates "the check found a problem" from
  "the check could not run", for the false-positive measurement in Open Work.
- **API**: `POST /intake/{id}/retry`; `service_error` on every turn;
  `health` on `GET /incidents/{id}`, which also feeds `requires_human_review`.
- **Clients**: reporter app shows "Try again" on a `service_retry` turn;
  responder console explains health-related holds in the review banner and
  shows a one-line note when calls were retried.
- **`llm/fake.py`**: queue an exception to script a model failure.
- **New `tests/test_health.py`** (15 tests). 143 tests total.

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

- **The three prompt changes for `animal_count` have not been run against
  real Gemini.** Tested with scripted replies only, like the rest of the
  prompts. Whether the model counts animals well from a photo is unmeasured.
- **A mass stranding is missed when nobody mentions the other animals.** Two
  people each photograph a different single dolphin 100 m apart: the second
  report is linked as a duplicate, both say one animal, and the count stays
  at one. Fixing it needs the photos compared.
- **The mass stranding distance and time (2 km, 24 h) are starting values**,
  not checked against real events. A mother and calf cannot be told from two
  unrelated animals; the banner says so when the count is exactly two.
- **Duplicate detection runs only at the end of intake.** The second reporter
  answers every question before the system notices the animal is already
  reported, and their photo and answers are not attached to the original
  incident. There is no count of how many people reported the same animal and
  no photo comparison.
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
10. Health trends across incidents (follow-up to the 2026-10-05 work): failure
    and retry rates per agent, an alert when they climb, and a way to
    regenerate a report that fell back to `report_unavailable`. The
    per-incident records are already being written.
