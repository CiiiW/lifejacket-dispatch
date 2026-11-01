# Drone progress tracker

Last updated: **2026-10-31** · Working branch: **charlotte-mini2-demo**

## Current scope and decisions

Focus on **drone patrol → animal sighting → coordinator review**. Reuse the
existing planner, flight records, photo agents and observation queue. The
small evaluation panel supports this work; a broader analytics product is not
the current priority.

Use real recorded drone footage for the next observation milestone. SITL is
engineering evidence about the flight worker, not evidence of wildlife
recognition or field performance. Keep simulation provenance distinct from real
camera evidence. Physical drone flight and a live camera connection are not
implemented or authorized by the current milestone.

## Verified state

| ID | Work item | Status | Evidence and remaining boundary |
| --- | --- | --- | --- |
| DR-01 | Bounded survey planning and review | Implemented | [Planner](../backend/lifejacket/drones/planner.py); checks and reviewed-plan identity. Battery/endurance estimates are not calibrated to a real aircraft. |
| DR-02 | SITL upload, supervised flight and saved telemetry | Implemented; simulator-tested | [Flight notes](sitl.md): GCP short survey completed, landed and disarmed; cancel recovered; injected link loss remained unconfirmed. These are synthetic flight results. |
| DR-03 | Individual-photo drone intake and advisory screening | Implemented; offline workflow-tested | [Observation workflow](drone_observation_handoff.md): original media, capture metadata, shared eight-group taxonomy, selected-target analysis, revisioned human review and case linking. No live camera ingestion. |
| DR-04 | Public-photo development baseline | Live run completed | [Run record](../research/public_condition_pilot/BASELINE_RUN_2026-10-23.md): 40 detection results, 38 assessments, 2 awaiting target selection, 0 failed cases. Human/expert reviews: 0 at the recorded checkpoint. Not an aerial benchmark. |
| DR-05 | Review page and small evaluation dashboard | Implemented; browser-verified on GCP | [Review page](../research/public_condition_pilot/review.html): stage counts, predicted/reviewed group coverage, saved-attempt telemetry and provisional same-target sign comparisons. No expert accuracy score. |
| DR-06 | Recorded drone-video intake and frame extraction | Implemented; first public wildlife video processed on GCP | [Mini 2 workflow](mini2_demo.md): original hash/copy, bounded JPEG samples, actual clip offsets, local review and optional existing detector. NOAA aerial opening samples processed successfully; actual Mini 2/toy footage and labeled detection evaluation remain outstanding. |
| DR-07 | Repeated-sighting grouping across frames | Provisional demo suggestions implemented; GCP tested | Conservative box/time association, ambiguity splits and source references; synthetic checks only. Real animal identity/tracking evaluation remains pending. |
| DR-08 | Video sighting review in the coordinator queue | Demo-only frame review implemented; GCP browser-verified | Separate toy/synthetic table, integrity-checked JPEGs, keep/reject audit and stale-edit protection. Real wildlife video review, target choice and case linking remain future work. |
| DR-09 | Live camera / companion upload and physical flight integration | Future work | Requires chosen hardware, actual capture/telemetry alignment and appropriate operator/site authorization. |

## DR-06 implementation and remaining validation

- [x] Define recorded-video metadata and distinguish capture time from frame offset.
- [x] Bound local recorded files by bytes, duration, dimensions and frame count.
- [x] Add opt-in demo frame API/importer behind the authenticated notebook proxy;
  whole-video uploads and app-level authentication remain future work.
- [x] Preserve the original video hash and extraction settings with every frame.
- [x] Extract a configurable, bounded frame sample and retain source offsets.
- [x] Record drone position as drone position; animal coordinates remain unknown
  unless a separate, validated geolocation method establishes them.
- [x] Connect sampled frames to existing detection without silently creating live
  incidents or treating no detection as a healthy animal.
- [ ] Run one actual recorded drone clip end to end; document its source/license,
  failures and observed results. A coded importer alone does not complete this item.

## Evaluation gates

The public-photo pilot checks the development pipeline. It cannot establish
patrol detection recall, aerial injury accuracy or tracking quality. Those
require representative real footage with target/frame annotations. Injury
performance also needs independent qualified review; the NOAA evaluation
sample is requested/planned, not received or evaluated in this session.

Human labels remain provisional. Compare signs only for the same target and
prediction version; exclude uncertain signs and record model/source exposure.
The dashboard does not show an accuracy percentage without expert ground truth.
NOAA evaluation material should stay held out from prompt/model tuning.

For a patrol demo, measure animal misses, false detections, repeated alerts,
incorrect sighting merges, usable-frame coverage, latency and review workload.
Report the number of clips/animals/views behind each result. Targets for these
metrics have not yet been agreed; do not invent a pass threshold.

## Access and reproducibility

- Current Mini 2 work is on `charlotte-mini2-demo`, based on main `3a323e9`,
  in an isolated GCP worktree. Prior `charlotte` staging is preserved.
  This branch has not been pushed to GitHub.
- Private review/evaluation app: authenticated GCP notebook `/proxy/8813/`.
  It binds to loopback and has no separate account system.
- Baseline run: `82cebed1b3e44e4c8b2352b22be595f9`; files and histories:
  `var/condition-baseline/pilot-v1-live/` on GCP. Original public photos are
  ignored by git and can be restored from the saved manifest.
- [Baseline and review instructions](../research/public_condition_pilot/README.md)
  explain the runner, fingerprint checks, exports and private serving command.
- Latest full backend validation: **507 passed on GCP** on 2026-11-01.
  Scripted tests check orchestration, not visual accuracy.

## Session log

### 2026-11-01 — Managed identity and persistent organization memberships

- Added managed ID-token verification with provider revocation/disabled-user
  checks, an authenticated `/access/me` session endpoint and database-backed
  organization/member state scopes. Personal sign-in grants no professional role.
- Added trusted offline additive-table initialization, explicit approvals and
  membership revocation with audit records. Existing case records are preserved.
- No real staff grants or cloud provider/IAM setup were performed. Legacy case
  routes remain outside this authorization boundary; frontend sign-in, verified
  geography and route-wide enforcement are next.
- Validation: 35 new tests and all 507 offline backend tests passed on GCP;
  lint and diff checks passed. One existing Starlette/httpx warning remains.
- Setup and limitations: [managed sign-in](network_signin.md).

### 2026-10-31 — Network source audit and first backend foundations

- Traced identity, map/detail/media/history, assignments, contact, ETA and schema
  behavior; [audit and rollout](network_implementation_audit.md) records concrete
  gaps. Existing raw routes remain unauthenticated; this is not live RBAC rollout.
- Added pure deny-by-default permission policy for verified principal/case
  snapshots: NOAA global submitted reports, approved state-wide center views,
  accepted field assignments, owner-only reporter view, participant contact/
  operations and narrowing lead/support/receiving/my-center filters.
- Added minimal owner-scoped reporter response contract with explicit acceptance,
  en-route, arrival, animal-located and closed phases. Only fresh en-route arrival
  estimates appear; no staff coordinates, contact details or internal transcripts.
- Fixed legacy multi-offer regression: additional offers/declines/acceptances
  preserve an active primary and travel/on-scene progress. Closed cases reject new
  offers/responses; matching response retries are idempotent. No automatic support
  membership or concurrent-update authorization is claimed.
- GCP validation: initial focused regression run 65 passed; full backend after
  the long-ETA check 472 passed (one existing dependency warning). Python lint
  and diff checks passed. No model calls, migrations or notifications.
- Next: verified sign-in/membership and geography migration, then enforce the
  policy on every read/mutation and replace hardcoded client identity. The new
  policy/projection functions are not yet adapters protecting legacy HTTP routes.

### 2026-10-31 — Assigned-rescuer contact and reporter response updates

- Recorded [response update design](reporter_response_updates.md): assigned-case
  contact, minimal reporter status/arrival ETA, manual animal-located confirmation,
  and optional reporter stay/leave with last-seen/access updates.
- Existing ETA/map and response statuses provide some building blocks. They do
  not yet enforce own-report/assigned-contact access or this minimal payload.
  ETA means approximate arrival, not resolution; accepted/on-scene/found differ.
- Reporter departure must not cancel the case or move the animal location.
  Current-case callbacks and status updates remain separate from future outreach.
  Requirements only; no contact, notification or security workflow claimed complete.

### 2026-10-31 — Reporter participation and nearby volunteer requirements

- Recorded [reporter participation design](reporter_participation.md): optional
  monitoring/future-rescue contact by selected phone/text channels, reusable
  participant profiles, consent changes, availability and nearby invitations.
- Separated animal report location from a volunteer's permitted current position;
  background sharing is optional, with saved-area/radius participation available.
- Defined accepted-task access and coordinator/qualification checks. Current
  callback phone storage does not implement subscriptions or future consent.
  This is design only; no contacts, locations or alert subscriptions provisioned.

### 2026-10-31 — Dashboard access and collaboration requirements

- Recorded [dashboard access design](dashboard_access.md): NOAA system-wide
  report visibility; verified rescue-center state scope; state-wide browsing
  plus my-center/assigned-to-me filters. This is design, not implemented RBAC.
- Separated case lead, supporting organizations, receiving center and individual
  assignments so nearby center B can assist a case destined for center A.
- Clarified network scope: reporter ↔ center, center ↔ center and center ↔ NOAA;
  shared case activity, help/acceptance, information requests and guidance.
  No outbound messaging or external agency integration is implemented here.
- Current hardcoded console identity and single assigned-responder model require
  backend identity/scope enforcement and explicit participation before rollout.
  Existing drone/data workflows and supported geography are unchanged.

### 2026-10-31 — Opening review complete and closer-view video run

- Inspected original opening frames and completed provisional/model-visible
  worksheets for all 12: five negative credit slates, four uncertain wide aerial
  views, three visible-colony views. Five possible-group regions and eight
  uncertain regions; no verified individual identities, recall or injury labels.
- Preserved the initial one-slate export and added the complete opening review.
- Scouted 32 samples across the original video offline; selected a ground-level
  pup sequence. Derived 8-second excerpt, retaining parent/excerpt hashes,
  source PTS 156.023–163.997s and transform details. No GPS/capture date inferred.
- GCP detection: 16/16 completed, 0 failures, boxes 2,2,2,3,3,3,3,2,2,2,2,2,1,1,1,1.
  Browser verified 16 images and 32 proposals. Clearer views produce individual
  animal proposals, but neither 32 proposals nor this ground-level clip measures
  distinct animals, aerial performance or injury accuracy.
- Run outputs, metadata and lineage saved; see [pilot record](noaa_video_pilot.md).
  New excerpt remains outside the toy/synthetic app queue. No code changed;
  existing 432-test code validation retained, with new JSON/media integrity checks.
- Next: define partial/background-target inclusion, draw per-animal reference
  boxes and review the new 16-frame excerpt before computing detection metrics.

### 2026-10-31 — Visible video regions and manual review worksheets

- Added numbered, responsive SVG detection boxes, escaped region descriptions,
  individual/group/not-animal/uncertain judgements, scene/presence/note fields and
  nullable whole-number missed-animal counts to the static video review page.
- Added `drone_video.py review` to verify source/frame hashes and prediction
  fingerprint before regenerating UI assets without new model calls.
- Provisional worksheet exports bind to manifest, source, frame and prediction
  fingerprints. Browser edits persist in that browser only; export is required
  for portability. Unreviewed/draft/reviewed remain separate. No server-side
  annotation API, accuracy score, expert labels or rescue operations added.
- GCP checks: 42 focused and 432 full backend tests passed (one existing dependency
  warning). Python lint, JS syntax and diff checks passed. Browser verified
  13 overlays and loaded images,
  required reviewer, fractional-count rejection, JSON preview/download request,
  null unknown counts and restore after reload. One actual opening credit slate
  provisionally reviewed by Codex; 11 animal/other frames remain unreviewed.
- This sample is model-visible project review, not independent ground truth.
  [Export example](../research/noaa_video_pilot/provisional-slate-review-2026-10-31.json).
- Next: closer-view continuous footage with per-target manual boxes/labels and
  independent expert evaluation. Region judgements alone are not a recall dataset.

### 2026-10-31 — GCP reconnection, recovery and first wildlife inference

- Connected browser access restored. Workbench ADC refreshed successfully using
  its existing credentials; no password/key export or access expansion needed.
- Workspace maintenance removed the temporary local checkout and its unpushed
  grouping/NOAA preparation commits. Recovered the intact GCP base and recreated
  grouping code, tests, fixture and notes from recorded work. Earlier local hashes
  `9bb39db` and `d3ab93c` are historical checkpoints, not available GCP commits.
- Restored source transferred to GCP. Full backend 420 passed (one existing
  dependency warning); Ruff, TypeScript checking, web export and diff checks passed.
- Browser verified 2 suggestions across 6 scripted rectangle frames, member links
  selecting the correct frame, loaded image and required review fields. These
  groups are disposable; reviews remain per-frame. No animal identity/count claim.
- NOAA source hash matched the earlier download. Prepared 12 first-section frames,
  verified media hashes, then ran Vertex Gemini 2.5 Flash: 12 completed, 0 failed.
  Boxes per frame: 0,0,0,0,0,0,0,0,1,3,4,5. See [run record](noaa_video_pilot.md).
- Descriptions refer to groups/colonies, not individual animals. Thirteen boxes
  cannot be interpreted as thirteen animals or verified sightings. No expert
  labels, accuracy score, injury analysis or real rescue cases were produced.
- Private NOAA review on notebook `/proxy/8917/review.html`; demo app `/proxy/8915/`.
  Real wildlife evidence stays outside the toy/synthetic queue. GitHub not pushed.
- Next: manual boxes/labels on a short continuous closer-view sequence; assess
  missed animals, false positives and group-region outputs before tracking claims.

### 2026-10-31 — Demo frame review queue

- Added opt-in demo-only frame import/list/photo/review API and a Demo review
  console tab. Separate table/IDs and no case-link, assignment or notification
  path; the existing California wildlife contracts are unchanged.
- Preserved source/frame hashes, rights notes, source offsets and optional saved
  detection results. Unknown capture time/location stays unknown. No model calls.
- Imports preflight the entire bundle, support identical retries without resetting
  reviews and reject metadata conflicts. Reviews require a name/note, retain
  history and use revision checks to reject stale writes.
- Full backend: 402 tests passed locally and on GCP (one dependency warning);
  focused video/demo tests: 27 passed locally and on GCP. TypeScript checking, Python lint and GCP web export passed.
- GCP browser: six synthetic frames imported; preview image loaded, blank review
  actions disabled, kept review saved, filter/reload preserved its audit history.
  These are generated test patterns, not toy/animal detection evidence.
- Private combined preview on loopback port 8915, notebook `/proxy/8915/`, using
  its own `var/mini2/demo-review.db` and evidence directory. Only demo API routes
  are served by this preview. Clear Expo's cache when changing API build config.
- Updated reproduction instructions. GitHub push remains pending.
- Next: actual toy clip/detection check, then repeated-sighting grouping (DR-07).
  Live streaming, GPS synchronization and physical flight remain unverified.

### 2026-10-31 — Mini 2 preparation from current main

- Pulled main to `3a323e9`; created `charlotte-mini2-demo` with the new map/UI work intact.
- Added recorded-video CLI, immutable source copy/hash, bounded sampling using actual
  presentation timestamps, local review page and explicit opt-in existing-agent detection.
- Added source/rights/evidence-kind metadata. Toy/synthetic evidence stays local;
  aircraft and animal location fields remain unknown until telemetry alignment exists.
- Focused decoder/integrity/failure tests: 13 passed. Full offline backend: 388 passed
  after installing the research test's pandas dependency; one existing dependency warning.
- No real aerial/toy clip, live model result, RTMP receiver, GPS synchronization,
  repeated-sighting association or physical flight is claimed. DR-06 is not complete.
- Hardware decision: preparing for original DJI Mini 2. Litchi/iPhone route and
  streaming behavior must be tested on the actual devices. No onboard Pi required.
- Continued on GCP CPU workbench in an isolated worktree at
  `/home/jupyter/lifejacket-mini2`; existing `charlotte` staging checkout preserved.
- GCP: 375 backend tests passed (13 video tests initially skipped without FFmpeg);
  all 13 video tests then passed separately with Conda FFmpeg 6.1.2. Ruff passed.
- System Debian FFmpeg installation returned stale-package 404s. Installed an
  isolated Conda environment under ignored `var/ffmpeg-env` instead.
- Generated a 6-second test pattern and verified six timestamped frames in the
  review page through authenticated Jupyter proxy port 8914. No model calls made.
- Implementation committed locally on GCP; not pushed to GitHub.
- Next: GCP validation, then actual toy footage and explicit app demo observation flow.

### 2026-10-23 — GitHub push readiness check

- Working tree was clean; refreshed `origin/charlotte` successfully. No upstream
  commits needed incorporation; 17 implementation/documentation commits were
  awaiting push before this log entry.
- `git diff --check` passed. Existing validation remains 361 full backend tests
  at the recorded checkpoint plus 9 focused review tests for the last UI increment;
  no implementation changed during this readiness check.
- Attempted a normal push to `charlotte` without force. Git exited 128 because
  GitHub credentials were unavailable (`could not read Username`). No push succeeded.
- Blocker: authenticate GitHub write access for this checkout, then fetch and
  push `charlotte` again. Browser sign-in has not supplied Git credentials.
- This log update is an additional local commit awaiting the same push.

### 2026-10-23 — Drone scope and progress tracking

- Confirmed drone work is the priority; accepted a small supporting evaluation panel.
- Reviewed current drone code and separated implemented photo/SITL workflows
  from missing video/tracking/live-camera capabilities.
- Added this tracker and linked it from the repository entry points.
- Added evaluation-panel views for processing, annotation coverage, shared
  animal groups, saved-attempt tokens/latency and provisional sign comparisons.
- Validation: JavaScript syntax, documentation links and diff checks passed.
  GCP browser checks confirmed the 38/2/0 processing counts, all eight group
  rows, token/latency values, no-review empty state and dashboard toggle.
  The browser console was clear; no human annotations were written.
  Nine baseline/review regression tests passed on GCP (one dependency warning).
- Next session starts at **DR-06**, using the checklist above. Actual video footage
  with usable source/license information is needed for the end-to-end check.

### 2026-10-23 — First live baseline and review workspace

- Ran the image-only Vertex baseline on 40 SHA-verified public photos.
- Results: 38 completed assessments, 2 multi-animal selection cases, 0 failed
  cases; no human annotations or expert evaluations created.
- Added versioned review storage, exposure tracking, stale-edit protection,
  original-photo viewing and export. No rescue cases or outbound messages created.
- Validation: 361 backend tests passed locally and on GCP; Python lint,
  JavaScript syntax and browser workflow checks passed.
- Full findings and caveats are in the linked baseline run record.

## How to keep this current

At the end of each drone work session, update the status table and append a
new dated entry at the top of the session log. Record what changed, actual
validation/results, remaining uncertainty, blockers and the next concrete task.
Link detailed evidence instead of repeating old architecture proposals. Mark
items complete only when their stated validation has run. Do not overwrite
older run results with newer ones or treat planned work as implemented.
