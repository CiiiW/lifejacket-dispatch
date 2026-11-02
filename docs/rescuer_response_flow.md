# Restricted rescuer contact and response updates

Implemented behind `NETWORK_CASE_ACTIONS_ENABLED=false` on the GCP demo branch.
The existing managed-auth IAM/proxy blockers are unchanged. No live staff grants,
real contact calls/texts, public deployment or actual rescue updates were made.

## Permissions

A permitted case view is not permission to contact a reporter or change a case.
NOAA can read submitted cases, and centers can browse their approved states.
Operational actions additionally require reviewed case/state metadata, active
participation by the selected organization, and a coordinator or accepted assigned
rescuer. Accepted support/receiving organizations count; suggested or withdrawn
relationships do not. Rescuer assignments must belong to the selected organization.

The offline case-review command can complete first review of a newly submitted
phone report, preserving its verified reporter owner and contact preferences while
setting reviewed state and an approved lead center. See `network_case_access.md`.
This does not create support relationships or individual assignments.

Reporter contact comes only from the phone-verified submitted reporter record,
with matching explicit case ownership. Legacy callback phones are not a fallback.
A staff request returns only the permitted call/text channels and reporter presence.
Phone numbers are never returned with statewide discovery, case cards, response
capabilities, reporter status, or audit metadata. Contact views are audited using
actor, selected organization, case, permitted channels and server time. Opening a
phone/message link is not proof of a call or delivered text; the API sends neither.

A reporter can withdraw current-case call/text consent through their phone-owned
case view. This does not cancel the report or affect future consents. Each staff
contact fetch rechecks current preferences/participation/assignment/identity.
Client contact details are cleared during 30-second/focus permission refreshes,
after response changes, on closed/denied/stale-error state, and on context change.
Previously seen contact details cannot be technically recalled; the UI's short
retention is not a substitute for current server authorization.

## Confirmed response lifecycle

`received → accepted → en_route → on_scene → animal_located → closed`

Users choose an event and explicitly confirm it happened. Arrival and finding the
animal are separate events. Models and old incident statuses do not advance the
reporter's response phase. Only the lead center's coordinator can close a case:

- `rescue_complete` requires `animal_located`.
- `unable_to_locate` requires `on_scene`.
- `no_response_needed` or `transferred` can close an active case as appropriate.
  A transferred closure records an outcome; it does not change center assignments.

No backward transitions or implicit NOAA override are offered. A withdrawal,
reassignment, correction or reopening needs a separately reviewed workflow.
The raw legacy intake status remains distinct from the confirmed response phase.
The case detail labels it **Intake record** and shows confirmed response separately.

Response writes use optimistic revisions. Stale or duplicate updates return 409;
clients do not automatically retry mutations. Each accepted write atomically records
the previous/new phases, revision, actor, organization, server time and optional
closure reason in an append-only response-event table. Existing database tables
are not altered; response version/event tables are additive.

The reporter's existing own-case projection reads the confirmed phase; it never
receives responder coordinates, staff contact, internal notes, audit data or raw
outcome notes. ETA remains unavailable until a reviewed, fresh arrival estimate
source is wired. There are no outbound status notifications in this change.

## API

- `GET /network/cases/{id}/response`: phase, revision and server-derived capabilities.
- `PATCH /network/cases/{id}/response`: explicit confirmation, expected revision,
  next phase and closure reason where relevant.
- `GET /network/cases/{id}/reporter-contact`: explicit staff contact reveal, with audit.
- `POST /reporter/reports/{id}/contact-preferences`: own phone-verified reporter only.

Professional routes retain bearer-token authentication and selected-organization
context. The network boundary permits only the enumerated response PATCH when
both network auth and case actions are enabled; unrelated legacy mutations remain
blocked. All responses use private/no-store. The reporter preference route retains
the existing managed-token POST-body transport; it does not weaken staff auth.

## Verification and remaining setup

Tests exercise two centers in the same state, accepted support participation,
assigned/unassigned/revoked responders, statewide observers, NOAA read-only access,
channel consent and owner-authorized withdrawal, stale revisions, lifecycle guards,
lead-only closure, atomic audit events and minimal own-reporter status. Client tests
check authenticated single PATCH requests with explicit revision/confirmation.
The separate fictional console fixture tests contact reveal, explicit confirmation,
phase changes, closure clearing and NOAA read-only behavior without actual auth,
API requests, calls, texts or rescue cases.

Keep live actions disabled until the minimal token-verifier IAM permission,
auth-preserving staff API endpoint and explicit real staff/case approvals are
verified. No live permission bypass or broad IAM role was introduced.

Validation: 99 relevant backend tests passed, including the restricted workflow/authorization and reporter suites; 11 console API tests and 4 reporter API tests passed. Both clients passed TypeScript checks and web exports. New backend routes/tests passed Ruff. Fictional browser checks passed for text-only contact, explicit confirmation, sequential response phases, closure clearing and NOAA read-only access. No live managed sign-in, contact delivery or public operational deployment is claimed.
