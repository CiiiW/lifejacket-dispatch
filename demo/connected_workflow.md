# Connected Rescue Demo

One story: a fictional dolphin report becomes a coordinator-reviewed case,
an offer is declined, a second offer is accepted, and the next shift can see
what changed and what remains open. Closure removes it from current carryover
without deleting its recorded events.

## Repeatable Offline Check

From the repository root with backend dependencies installed:

```bash
pytest backend/tests/test_api.py::test_connected_rescue_workflow -v
```

This executes the real HTTP routes against disposable SQLite and photo
storage. It uses scripted model choices, placeholder image bytes, unavailable
environmental context, and a fictional organization. It makes no model calls,
uses no application database, sends no notifications, and rescues no animal.
It validates workflow wiring, not model quality or a rendered UI.

Assertions cover completed intake, unchanged case state after model checks,
approval requirements, needs-assignment and awaiting-response checks,
decline/accept history, coordinator references, current carryover, closure,
and outcome events.

The scripted dolphin case also retains a human-review check after acceptance.
An accepted assignment is not review acknowledgment; that acknowledgment is
not stored yet. Closing the case suppresses pending checks but does not prove
the review occurred.

## Local UI Walkthrough

Use a disposable local database, never operational rescue records. Start the
backend and console using the root and [client README](../clients/README.md).
Live intake and Check Coordination need Vertex credentials and make billable
model calls; handover does not. Keep the unauthenticated backend local.

1. Submit a test report through the reporter app or `/docs`. Use a photo you
   have permission to show and answer clarification questions. Record its ID.
2. Open the case in the console. Show the evidence, uncertainty, urgency,
   report, and candidate responders. Do not claim permit validation.
3. Click Check Coordination. Show source references and proposed human review,
   not autonomous dispatch. A held result is a visible safety outcome.
4. In `/docs`, use `POST /responders/assign` with the incident ID, a test
   responder ID, and a fictional `approved_by`. Record the assignment ID.
5. Check again: an unanswered offer should produce `awaiting_response`.
   Decline it with `POST /responders/assignments/{id}/respond`, using
   `{"accept": false, "note": "Demo only: team unavailable"}`. Check again.
6. Create a second offer and accept it with `{"accept": true}`. Review the
   assignment records; decline history must remain visible. This does not
   prove spare capacity or eligibility.
7. Open Handover. Select a timezone-qualified window covering the exercise
   and load it. Show recorded changes and current carryover, not a fictional
   AI recap. Events begin at rollout; older changes are not reconstructed.
8. Log a clearly labeled test outcome. Reload handover: the case leaves
   current carryover, while response and outcome events remain.

The HTTP check exercises this story; mobile/desktop visual verification is
still outstanding. Live model decisions can fail, so retain the offline check
as an explicitly labeled fallback rather than passing it off as live AI.

## Separate Extensions

Duplicate sightings and mass-stranding grouping belong to intake/triage, but
are not covered by this single-case demo. Demonstrate them separately with
the dedicated tests, then show their case links in coordinator review.
Use [the existing photo seeder](README.md) only for live intake fixtures; its
distance validation intentionally discourages duplicate demo rows.
