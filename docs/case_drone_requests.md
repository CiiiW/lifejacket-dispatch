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

Scores are model/assessment confidence values, not measured accuracy. The condition model
may persist a default zero confidence; this remains a review signal rather than a diagnosis.
Deterministic severity confidence and weather lookup failures are not used as image-confidence triggers.
No model calls or aircraft commands are made when generating suggestions.

Review suggested request opens an editable verification draft. Submission requires an explicit
coordinator action; the server checks current evidence again before accepting the suggestion ID.
The new request remains requested until separately approved. Its source confidence/threshold snapshot is saved.
A stable evidence/policy fingerprint and existing unique creation key prevent duplicate creation.
Any active verification request suppresses additional suggestions for that case.
After a suggested request is declined, cancelled or reviewed, unchanged evidence does not generate it again.
New assessment evidence can generate a fresh suggestion once no verification request is active.
Closed, unresolved-intake and duplicate cases do not generate suggestions.

The fictional UI fixture includes low group confidence, low condition confidence, confident broader group,
urgent response and missing-score scenarios. These controls are outside the production component.

Suggestion increment validation: 69 backend regression checks passed; final suggestion suite 34 passed.
TypeScript, lint, fixture build and 13 network transport checks passed. Browser scenario checks passed.
