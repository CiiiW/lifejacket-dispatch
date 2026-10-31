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
| DR-06 | Recorded drone-video intake and frame extraction | Local implementation; synthetic tests passed | [Mini 2 workflow](mini2_demo.md): original hash/copy, bounded JPEG samples, actual clip offsets, local review and optional existing detector. Actual drone/toy footage and live detection evaluation remain outstanding. |
| DR-07 | Repeated-sighting grouping across frames | Not started | Preserve frame evidence and uncertain associations; evaluate missed animals, duplicate alerts and incorrect merges on real footage. |
| DR-08 | Video sighting review in the coordinator queue | Not started | Clip/frame references, target choice and location uncertainty; reuse existing observation review before any case link. |
| DR-09 | Live camera / companion upload and physical flight integration | Future work | Requires chosen hardware, actual capture/telemetry alignment and appropriate operator/site authorization. |

## DR-06 implementation and remaining validation

- [x] Define recorded-video metadata and distinguish capture time from frame offset.
- [x] Bound local recorded files by bytes, duration, dimensions and frame count.
- [ ] Add authenticated video uploads / demo observation API; local CLI is not an upload service.
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

- Code and notes are committed on `charlotte`; GCP receives matching source
  patches. GitHub push remains pending repository authentication.
- Private review/evaluation app: authenticated GCP notebook `/proxy/8813/`.
  It binds to loopback and has no separate account system.
- Baseline run: `82cebed1b3e44e4c8b2352b22be595f9`; files and histories:
  `var/condition-baseline/pilot-v1-live/` on GCP. Original public photos are
  ignored by git and can be restored from the saved manifest.
- [Baseline and review instructions](../research/public_condition_pilot/README.md)
  explain the runner, fingerprint checks, exports and private serving command.
- Latest full backend validation: **361 passed** locally and on GCP on
  2026-10-23. Scripted tests check orchestration, not visual accuracy.

## Session log

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
- User requested GCP as the working environment. CPU workbench started; source
  transfer and validation there are pending at this checkpoint.
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
