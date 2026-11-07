# Case-linked drone observation requests

Status: implemented on `charlotte-case-drone-requests`; not deployed.
Hardware: Charlotte has purchased an original DJI Mini 2.
This increment connects case requests to reviewed still-image evidence; it does not control aircraft.

## Workflow

1. Open a reviewed case in Rescue network.
2. The active lead coordinator creates a verification or monitoring request.
3. Record the question to answer, reason, escalation criteria and execution kind.
   Monitoring requires a future next-review time. This is a recorded plan, not an automated notification.
4. Approve with a responsible operator. For operator flights, starting collection requires explicit
   operator confirmation of site permission, weather, range and battery feasibility.
5. Attach JPEG/PNG/WebP photos or extracted frames while collection is in progress.
6. Mark evidence ready, then review it as answered, still uncertain or escalation needed.
   Record the finding and optionally the next review time.
7. Findings remain a case-linked addendum; original intake and rescue response status are preserved.

Requested → approved → in progress → evidence ready → reviewed.
Decline, cancellation and failure paths are retained. Flight completion is not equivalent to answering the question.
No aircraft commands, automatic launch, model calls, alerts or automatic rescue escalation are introduced.

## Recorded NOAA footage

Choose recorded footage demo, use a fictional case, and extract still frames using the existing recorded-video tools
(`docs/mini2_demo.md`). Upload the selected frames to the request.
Record the exact HTTPS video source, credits/reuse terms, actual source capture time if known,
and clip offset. Unknown times/animal coordinates stay null; aircraft coordinates are not animal coordinates.
A source being hosted by NOAA is not by itself a reuse license.
This increment does not download or license any NOAA video.

Sample footage is permitted only on recorded-demo requests. Operator-flight requests require operator captures
with a capture timestamp. All evidence is held for human review, independent of model confidence.
A recorded demo never claims a requested physical flight occurred.

## API and storage

Feature flag: `CASE_DRONE_REQUESTS_ENABLED=true`, alongside existing managed network authentication.
It defaults off. Current managed-auth/IAM/proxy launch prerequisites still apply.
Routes:
- GET/POST `/network/cases/{case_id}/drone-requests`
- GET/PATCH `.../{request_id}`
- POST `.../{request_id}/evidence` (multipart metadata JSON + photo)
- GET `.../{request_id}/evidence/{evidence_id}/photo`

Only involved approved staff can read request details. Only the active lead center coordinator can mutate.
Assigned operator names are descriptive responsibility records, not permission grants.
Authentication and current database membership are rechecked on every request.
Creation keys prevent identical retries creating duplicate requests.
Every state/evidence change uses compare-and-swap revision checks and transactional append-only events.
New tables are additive: case_drone_requests, case_drone_events, case_drone_evidence.
Persist the database and DRONE_EVIDENCE_DIR together. No existing tables require altered columns.
Evidence retains a hash and immutable source metadata; local storage paths are not returned.

## Development and verification

Base: fetched GitHub main `3a323e9`, then fast-forwarded to existing local `charlotte`/`charlotte-mini2-demo`
commit `9baad25` for the newer case permissions and phone-report review dependency.
Existing worktrees were preserved. This branch includes that dependency; do not propose it as an independent diff
against the older main without reviewing the parent changes.

- Backend: `python -m pytest backend/tests/test_drone_requests.py`
- Types: `npx tsc -p clients/responder_console --noEmit`
- UI fixture: `npm ci`, install responder-console dependencies, then `npm run demo:drone-requests`.
  Opens on loopback port 8084. No backend, credentials or real case data.
- UI fixture uses synthetic frames only. API tests use a temporary database and test identity overrides;
  there is no production mock-auth flag.

## Remaining work

Automatic low-confidence suggestions are implemented as described below; calibration and additional evidence-gap rules remain future work.
The existing 0.90 identification threshold is unvalidated and is not used as an automatic flight rule.
Monitoring recurrence, notifications, operator self-service, video upload/automatic frame import into requests,
live managed-auth deployment and Mini 2 flight/camera integration remain future work.

Validation on 2026-11-06: full backend 579 passed / 15 skipped; final focused drone suite 13 passed.
TypeScript, lint and fictional browser monitoring lifecycle passed.


## Automatic low-confidence suggestions

Suggestions are derived on the case request GET endpoint after completed intake, using
DRONE_VERIFICATION_CONFIDENCE_THRESHOLD (default 0.90, provisional and uncalibrated).
The same endpoint enforces existing case access. GET does not create requests or events.

| Signal | Source | Rule |
| --- | --- | --- |
| Animal group uncertainty | Identification candidate probabilities pooled by animal group | Maximum known group probability below threshold |
| Condition uncertainty | Explicit persisted assessment.injury.confidence | Confidence below threshold |
| Missing/invalid confidence | No numeric evidence | No score is invented; manual requests remain available |
| Exact species uncertain, broader group confident | Same-group candidate probabilities | No identification-only suggestion |
| Urgent case | Severity respond/critical or critical condition flags | Evidence review may run in parallel; response must not wait |

Scores are model/assessment confidence values, not measured accuracy. Missing condition confidence is preserved as null by the parser and domain model and displayed as Unknown.
Explicit zero remains a genuine low-confidence value. Existing legacy zero values cannot be retrospectively
distinguished from old defaults without source evidence and are not silently rewritten.
Deterministic severity confidence and weather lookup failures are not used as image-confidence triggers.
No model calls or aircraft commands are made when generating suggestions.

Review suggested request opens an editable verification draft. Submission requires an explicit
coordinator action; the server checks current evidence again before accepting the suggestion ID.
The new request remains requested until separately approved. Its source confidence/threshold snapshot is saved.
A stable evidence/policy fingerprint and existing unique creation key prevent duplicate creation.
Any active operator-flight verification request suppresses additional operational suggestions for that case.
Recorded-demo requests do not suppress or consume operational suggestions. Their idempotency keys
are namespaced separately so the same evidence can support both a demo and an actual request.
After an operator-flight suggested request is declined, cancelled or reviewed, unchanged evidence does not generate it again.
New assessment evidence can generate a fresh suggestion once no verification request is active.
Closed, unresolved-intake and duplicate cases do not generate suggestions.

The fictional UI fixture includes low group confidence, low condition confidence, confident broader group,
urgent response and missing-score scenarios. These controls are outside the production component.

Suggestion increment validation: 69 backend regression checks passed; final suggestion suite 34 passed.
TypeScript, lint, fixture build and 13 network transport checks passed. Browser scenario checks passed.


## Review fixes — 2026-11-06

- A recorded demo can be created or cancelled without hiding the operational suggestion.
  This also handles older demo rows using an unscoped creation key.
- Explicitly unidentified animals and explicit retake gaps produce a qualitative
  identification-evidence-gap suggestion. No animal-group probability is manufactured.
  Confident broader animal groups continue to avoid species-only verification requests.
- Missing condition confidence survives parsing, serialization and database round trips as null.
  The case panel displays Unknown. Confidence 0.0 is still treated as an explicitly supplied score.
- New regression tests reverse all three reproduced review failures, covering both the schemas
  and the real API with disposable data. No existing case data was rewritten.

Review-fix validation: full backend 620 passed / 15 skipped; final focused suite 53 passed.
TypeScript, lint, fixture build, 13 transport tests and browser checks passed.

## Connected backend scenario

Run `python scripts/run_connected_scenario.py --with-drone` in the backend environment.
The completed run passed 68 real API checks using one disposable case/database.
See [connected drone scenario](connected_drone_scenario.md) for isolation boundaries,
the saved report and regression commands. AI, SMS and aircraft operation remain simulated.


## Monitoring follow-through

Participating coordinators and assigned rescuers can read `GET /network/monitoring`.
Only an active case's lead coordinator can record a decision at
`POST /network/cases/{case_id}/drone-requests/{request_id}/monitoring`.
The queue uses existing verified membership, state and case participation rules;
reporters, NOAA accounts and unrelated centers do not gain monitoring access.

A monitoring request, or any observation with an explicit next review time, remains
in the queue until a coordinator records continue, escalate or finish. Overdue
items appear first; due soon means within 24 hours. This is a display window,
not a recommended observation interval. Missing/invalid legacy schedules are visible.
Closed rescue cases are excluded. The queue refreshes every 30 seconds while open;
there are no background notifications.

Complete, decline, cancel or fail the current observation before deciding its next
step. Continue requires a future time and atomically creates a same-case follow-up,
retaining the evidence collection mode, objective and escalation criteria. Its
status is requested and it needs separate approval. Server-assigned previous/root
request IDs preserve the chain. Revision checks and the unique follow-up key
reject repeat decisions. A failed transaction leaves the parent and child unchanged.

Escalate records the reason for coordinator action; it sends no alert or aircraft
command. Finish stops this monitoring branch. Neither changes rescue response
status, severity or the original intake. Decisions and linked requests remain in
the request history. Recorded demonstrations remain distinct from operator flights.

The queue currently scopes cases in SQL and sorts eligible observations in memory
before pagination; indexed queue queries will be needed for larger deployments.


## Coordinator attention and overdue reminders

`GET /network/monitoring/attention` is a permissioned in-app inbox for participating
cases. An escalation decision remains visible after it leaves the monitoring
queue. A reviewed outcome of escalation_needed also creates an attention item.
Overdue review times create reminders without waiting for a coordinator to open
the individual case. Both appear when the workspace next loads and refresh
every 30 seconds while it is open.

Only the active lead coordinator can acknowledge an item, with an explicit note
and confirmation. The acknowledgment is stored in the request and immutable event
history using a revision check. Acknowledging does not approve, resolve, dispatch
or reschedule anything. Reminder identities include the review time, so a new
schedule can create a new reminder without repeating acknowledged reminders for
the same schedule. Closed cases are excluded; supporting staff and assigned
rescuers can read but cannot acknowledge.

These are in-app reminders. Email, text, push notifications and background
delivery while the workspace is closed are not configured.

## Evidence comparison

The selected observation includes a comparison with its linked previous request,
or another observation from the same case. The view shows the stored intake
assessment, each observation finding, evidence provenance, capture time and
authenticated image controls. The intake assessment is the current stored
record, not an immutable historical snapshot or a reporter transcript. No raw
reporter contact or transcript is returned. Original reporter photos are not
included in this view. Images are loaded through the existing case-scoped
authenticated evidence endpoint, and preview URLs are revoked on context changes. A failed comparison/image request also cancels pending image loads and clears the observation panel.
Comparison does not automatically infer deterioration or recovery.

See [threshold evaluation](drone_threshold_evaluation.md) for the offline
evaluation runner, synthetic results and requirements for reviewer-labeled data.
