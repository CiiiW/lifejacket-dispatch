# Restricted network case reads

The backend now has a separate authenticated case API. The dashboard is not connected yet. Network mode is disabled in the current private demo configuration; no real cases or staff grants have been enrolled by this work.

## Behavior

| Endpoint | Access and response |
| --- | --- |
| `GET /network/cases` | Approved NOAA context sees enrolled submitted cases nationally. Approved center coordinators see enrolled submitted cases in their verified approved states. Field rescuers also need accepted personal assignment and accepted participation by their selected organization. |
| `GET /network/cases/{id}` | Same professional visibility as the list. Missing and inaccessible cases both return 404. |
| `GET /network/reports/{id}` | Only the account explicitly bound to the report through reviewed metadata. Returns the minimal reporter response contract, no staff positions or contact details. |

Use managed tokens and organization selection as documented in [sign-in setup](network_signin.md). Professional list/detail fields are enumerated: case ID, status, reviewed state, animal coordinates, animal group/species, severity, lead organization and creation time. No raw report, transcript, phone number, staff location, related-case reference or global aggregate is included. Media/contact endpoints are not part of this slice.

The `scope` query parameter narrows the authorized professional list: `all_allowed`, `my_center`, `assigned_to_me`, `leading`, `supporting`, `receiving`. Pending organization invitations and unaccepted assignments do not qualify. `limit` (1–100) and `offset` (0–100000) apply **after** database authorization predicates. Filters cannot widen state or assignment access. Rows sort by creation time descending then case ID; this is offset pagination, not a stable snapshot across concurrent inserts.

Reporter response phases are explicit server records; they are not inferred from model detections or legacy incident statuses. This slice has no response-event editing UI. No ETA is supplied yet: do not reuse the legacy endpoint that exposes staff coordinates. Leaving remains voluntary and does not cancel the case.

## Network mode boundary

With `NETWORK_AUTH_ENABLED=true`, middleware allows read requests to `/access/me`, `/network/*` and `/health`. Every current legacy endpoint, including intake, case detail/photos, staff location/ETA, history, drone operations, coordination, mutations and API documentation, is blocked with 403. CORS preflight requests may pass but cannot read or mutate case data. Unknown network paths return normal 404/405 responses and grant no access.

This deliberately creates a **read-only network mode**. It does not silently secure each legacy operation. Existing clients cannot use their old endpoints in that mode. Before enabling it for users, finish authenticated intake, frontend sign-in and case views, scoped media/contact, response events and permitted coordination mutations. Keep the current demo service private while the flag is false: its legacy routes retain prototype behavior.

The boundary sets private/no-store caching for network-mode responses, including errors. New network endpoints still fail closed when managed sign-in is disabled/unconfigured. No alternate trusted-header identity is accepted.

## Reviewed metadata and additive migration

Three new tables preserve old incidents without adding or reinterpreting existing columns:

- `network_cases`: submitted status, explicit account ownership, reviewed state and provenance, lead organization and reporter response phase.
- `network_case_organizations`: separate accepted supporting/receiving participation.
- `network_case_assignees`: accepted individuals bound to their organization for this case.

Back up and verify the target `DATABASE_URL`, initialize access tables first, then run `PYTHONPATH=backend python scripts/network_case_admin.py init`. Initialization is additive and enrolls no cases. Normal app startup also creates missing tables through the existing `init_db` mechanism.

A trusted operator can run `network_case_admin.py review --help` to enroll one independently reviewed submitted incident. The command requires an existing case, valid reviewed state, reviewer reference and explicit `--confirmed-submitted` attestation. Optional account ownership must reference an enabled account and must be verified outside the command; optional lead must be an approved center for that state. Review records an audit event and starts the reporter phase at `received`. It rejects silent re-enrollment/ownership overwrite. It does not send notifications or grant personal assignments/support relationships.

Old `reporter_id`, location/place text, offers and `assigned_responder_id` grant no network access automatically. Unenrolled cases and draft records stay out of professional results. NOAA may read enrolled submitted reports whose state is still unknown; center access requires reviewed state. The ordinary review CLI requires a valid state; any separate unknown-state enrollment workflow is still future work. Do not enroll toy/synthetic drone evidence in the real incident network. Fixtures in tests are fictional.

## Remaining work

Frontend/provider configuration; authenticated intake and account ownership binding; approved geography review/backfill; scoped evidence and reporter contact consent; help requests and acceptance/handoffs; individual assignment and status-event workflows; fresh arrival estimates; volunteer contact/availability/consent and notifications. The database relationships are a foundation, not a completed center-to-center workflow or live dashboard.

## Validation

On GCP: 30 new HTTP/access/admin tests and all 537 offline backend tests passed,
with one existing Starlette/httpx warning. Python lint and diff checks passed.
A disposable CLI initialization smoke preserved a fictional existing incident
and enrolled zero cases after two runs. Provider verification is mocked for
HTTP integration tests; live managed sign-in and frontend behavior are not tested
by this backend-only increment.
