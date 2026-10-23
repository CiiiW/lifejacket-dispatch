# Drone progress tracker

Last updated: **2026-10-23** · Working branch: **charlotte**

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
| DR-05 | Review page and small evaluation dashboard | Implemented; validation pending this session | [Review page](../research/public_condition_pilot/review.html): stage counts, predicted/reviewed group coverage, saved-attempt telemetry and provisional same-target sign comparisons. No expert accuracy score. |
| DR-06 | Recorded drone-video intake and frame extraction | **Next; not started** | Preserve media hash, timestamp offsets and capture metadata; produce a bounded frame sample for the existing detection agent. |
| DR-07 | Repeated-sighting grouping across frames | Not started | Preserve frame evidence and uncertain associations; evaluate missed animals, duplicate alerts and incorrect merges on real footage. |
| DR-08 | Video sighting review in the coordinator queue | Not started | Clip/frame references, target choice and location uncertainty; reuse existing observation review before any case link. |
| DR-09 | Live camera / companion upload and physical flight integration | Future work | Requires chosen hardware, actual capture/telemetry alignment and appropriate operator/site authorization. |

## Next implementation: DR-06

- [ ] Define recorded-video metadata and distinguish capture time from frame offset.
- [ ] Validate video uploads and bound bytes, duration, decoded dimensions and extracted frames.
- [ ] Preserve the original video hash and extraction settings with every frame.
- [ ] Extract a configurable, bounded frame sample and retain source offsets.
- [ ] Record drone position as drone position; animal coordinates remain unknown
  unless a separate, validated geolocation method establishes them.
- [ ] Connect sampled frames to existing detection without silently creating live
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

### 2026-10-23 — Drone scope and progress tracking

- Confirmed drone work is the priority; accepted a small supporting evaluation panel.
- Reviewed current drone code and separated implemented photo/SITL workflows
  from missing video/tracking/live-camera capabilities.
- Added this tracker and linked it from the repository entry points.
- Added evaluation-panel views for processing, annotation coverage, shared
  animal groups, saved-attempt tokens/latency and provisional sign comparisons.
- Validation: JavaScript syntax and diff checks passed; browser validation pending.
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
