# Coordination Tools

Four read-only functions in `lifejacket.services.coordination` are available
to Python callers and through FastAPI. They are tools, not agents or subagents.
No new model calls or dispatch actions are made by these tools.

| Python function | HTTP endpoint | Result |
| --- | --- | --- |
| `get_incident_history(session, incident_id)` | `GET /coordination/incidents/{incident_id}/history` | Current snapshots, recorded events, messages, photos, assignments, closing logs, and directly linked duplicate reports |
| `get_assignments(session, incident_id)` | `GET /coordination/incidents/{incident_id}/assignments` | Offers and latest responses, including declines |
| `get_pending_tasks(session, incident_id)` | `GET /coordination/incidents/{incident_id}/pending-tasks` | Derived checks for missing assignments, unanswered offers, and human review |
| `get_available_responders(session)` | `GET /coordination/available-responders` | Active, on-duty responders and their active assignment IDs |

Unknown incident IDs return HTTP 404. History requested using a duplicate ID
resolves to its original and includes that original's direct duplicates.
Assignment and pending-task tools remain scoped to the exact requested ID.
Closed or duplicate cases do not generate pending tasks.

## Using The Tools

Run the existing backend, then open `/docs` and expand **coordination tools**.
For example, after starting intake:

```bash
curl http://localhost:8000/coordination/incidents/INCIDENT_ID/history
curl http://localhost:8000/coordination/incidents/INCIDENT_ID/pending-tasks
curl http://localhost:8000/coordination/available-responders
```

For an internal caller with a database session:

```python
from lifejacket.services.coordination import get_incident_history, get_pending_tasks

evidence = get_incident_history(session, incident_id).model_dump(mode="json")
pending = [task.model_dump(mode="json") for task in get_pending_tasks(session, incident_id)]
```

## Evidence Boundaries

- History is not a complete event log: current status and latest assignment
  response are snapshots, not reconstructed transitions. Explicit
  `recorded_event` entries now preserve application changes after rollout.
- Source references identify database records. Recorded timestamps do not
  necessarily identify when the animal was observed.
- Pending tasks are inferred from recorded state, not persisted tasks with
  owners, deadlines, or completion. Review acknowledgment is not stored yet.
- On-duty is a recorded flag, not evidence of spare capacity or eligibility
  for a particular incident. Organizations without that flag are omitted.
- These endpoints inherit the prototype's existing lack of authentication.
  History includes reporter conversation text; do not expose it publicly.
- The coordination agent uses these tools through a bounded execution loop,
  described below. The read-only endpoints themselves make no model calls.

## Coordination Agent

`POST /coordination/incidents/{incident_id}/check` asks the configured Gemini
model what needs attention on one case. It uses the existing Vertex AI client,
model settings, retries, and system principles. It requires ADC credentials
for live execution, just like intake.

```bash
curl -X POST http://localhost:8000/coordination/incidents/INCIDENT_ID/check
```

Both Expo clients can import `coordination` from their existing `lib/api`
re-export and call `coordination.checkCase(incidentId)`. The typed response
includes attention items, source references, tool calls, and limitations.
The responder incident detail now has a user-triggered `Check Coordination`
control. It shows attention items, proposed next steps, source references,
responder options, tool calls, and limitations. Held results and transport
errors remain visible. Checks are never automatic: each makes live model calls.
Leaving the detail screen aborts the browser request; this does not guarantee
that an already-started backend model call is cancelled. Changing case or its
recorded update timestamp clears the previous check. Results are snapshots,
not continuously refreshed incident state.

The model chooses one registered tool at a time using schema-constrained JSON.
The application executes it, returns the observation to the model, and repeats.
This is application-managed tool calling, not native SDK function calling.
History, assignments, and pending tasks must be retrieved before finishing.
Availability is optional. No tool can be called twice, and tool arguments are
fixed to the incident in the URL. The agent cannot query a different case.

Final attention items are assembled from the retrieved pending checks and fixed
next-step templates. The model may order those checks and select retrieved
on-duty responders for coordinator review, but cannot invent or omit checks,
write findings in unsupported prose, or declare a responder eligible.

Failures, invalid decisions, repeated calls, oversized evidence, and budget
exhaustion return `status: held_for_review` with no proposed actions. A completed
check with no attention items means no supported checks were found; it is not
an assertion of safety. Nothing is dispatched, sent, or saved by this endpoint.

Limits are configured through `COORDINATION_MAX_ROUNDS` (default 6, range 4-12)
and `COORDINATION_MAX_EVIDENCE_CHARS` (default 60000). Underlying model requests
also use the existing retry and output limits. Offline tests use scripted
model choices to exercise real tools, not to measure Gemini decision quality.

## Five-Case Evaluation

The runner creates a fresh in-memory database for each fictional case. It never
opens the application's incident database. Cases cover declined, unanswered,
accepted, human-review, and closed records. Success requires exact expected
attention items, all required tools, no repeated tools, bounded decisions,
unchanged incident and assignment state, and preserved human approval.

```bash
make coordination-eval ARGS="--output research/coordination_evaluation/offline.json"
# Once ADC is configured and project access is granted:
make coordination-eval ARGS="--live --output research/coordination_evaluation/live.json"
```

Live mode records model-reported prompt/output tokens, attempts, tool choices,
and per-case wall time. Missing usage is null, never presented as zero cost.
Missing ADC writes a blocked result and exits before model calls. Offline mode
uses prescribed tool choices and cannot establish that Gemini selects tools
well. Review live failures before making the console call this endpoint.

### Live Results: 2026-10-07

Executed in an isolated JupyterLab directory using Python 3.11 and Vertex AI
`gemini-2.5-flash`. No application incident database was opened.

- `research/coordination_evaluation/live_initial.json`: 4/5 passed. The declined
  assignment case repeated a tool request and was held for review without
  changes to the fixture's incident or assignment state.
- The prompt now includes application-controlled workflow state and lists only
  tools not already retrieved. The repeat-request guard remains enforced.
- `research/coordination_evaluation/live_after_prompt_fix.json`: 5/5 passed;
  this is the current post-fix result, not the initial result. Per-case elapsed
  time was 5.93-9.38 seconds, with 21 model decisions total. Reported usage was
  32,745 prompt tokens and 773 output tokens; no billing estimate is inferred.

This was one run per case before and after the change, not a reliability
estimate, responder-policy validation, or comparison against a deterministic
baseline. All 232 backend tests also passed after the change.

## Event History And Shift Handover

The new `incident_events` table records creation and changes to incident status,
assigned responder, duplicate link, severity, and required-review flag through
the repository and responder endpoints. Assignment offers preserve the
caller-supplied approval reference; responses preserve before/after status and
the response note. Outcome events reference the closing log. Event writes use
the same transaction as the corresponding update, and UTC recording times.
They are application records, not a tamper-proof audit log or authenticated
proof of who acted. Direct database writes bypass recording.

Restarting the backend runs `init_db()` to create the new table; no existing
columns are changed. Existing cases are not backfilled. Legacy snapshot times
have no timezone, so do not treat their ordering against new UTC events as an
exact chronology.

`GET /coordination/handover` requires `start` and `end` with timezone offsets,
normalizes them to UTC, and accepts a positive window of at most seven days.
Changes cover `[start, end)`; carryover is current at generation, not historical
state at the shift boundary. All open nonduplicate cases are included, even
unfinished intake and cases opened before the selected shift.

The console's `Handover` tab defaults to the previous eight hours with editable
timestamps and an explicit load action. It shows current carryover, pending
checks, recorded changes, source references, and truncation warnings. Case links
open incident detail. This is a deterministic read-only view, not an agent or
model-generated recap. No model calls, notifications, or approvals occur.

Retrieval is bounded to 500 events and 200 carryover cases with explicit flags
when incomplete. Scope is installation-wide: center ownership, authentication,
shift ownership, and review acknowledgment are not implemented. Like the other
prototype endpoints, this must not be publicly exposed.

Verification: 14 new backend tests cover writes, no-op changes, rollback,
creation, review changes, outcome references, timezone normalization, half-open
windows, invalid windows, limits, legacy records, history inclusion, and HTTP.
Console typecheck passed. Browser verification remains blocked by macOS's
native CSS-library loading policy; mobile/desktop layout is not verified.
