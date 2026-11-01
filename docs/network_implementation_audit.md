# Rescue network implementation audit

Working branch: `charlotte-mini2-demo`. Date: 2026-10-31.

## Findings from the current source

| Area | Existing building blocks | Concrete gap |
| --- | --- | --- |
| Identity | Responder/organization directory; optional reporter ID | Console hardcodes one responder ID. Roles/memberships are not authenticated. Client IDs/actor strings are not authorization. |
| Geographic scope | Incident coordinates/place name; responder response-area text | No normalized, verified case state or approved organization state memberships. Place-name text cannot enforce state access. |
| Assignment | Offers, acceptance/decline, one primary responder; event history | Before this increment, a new offer could downgrade an active case and another team's decline could clear the accepted primary. The regression is fixed below. No explicit lead/support/receiving relationships. |
| Professional reads | Incident map/list/details/photos/transcript; coordination tools/history/handover | Legacy reads do not enforce viewer membership/state/participation. Scoping only the map would leave detail/media/history paths open. |
| Contact | Optional incident callback phone | Professional detail includes contact data without assignment-scoped identity enforcement. No channel/purpose consent model or verified participant profile. |
| Reporter status | Accepted/en_route/on_scene states, ETA endpoint and tracking screen | ETA API includes staff coordinates; accepted/on_scene rows are returned alongside en_route. Base-position fallback and freshness are not clearly distinguished. Animal located is not a separate verified event. |
| Consent/nearby help | Responder duty/location flags | No reporter participation database, granular future consent, invitation acceptance, location expiry or outbound-delivery service. Reporter and responder identities must not be conflated. |
| Storage | SQLAlchemy tables and create_all | create_all does not alter existing columns. New memberships/geography/participation/consent need reviewed migrations and backfill rules. |

Relevant source: `clients/responder_console/App.tsx`, `clients/reporter_app/src/screens/TrackScreen.tsx`,
`backend/lifejacket/api/routes/{incidents,intake,responders,coordination}.py`,
`backend/lifejacket/models/{tables,db}.py` and `backend/lifejacket/services/events.py`.

## First implementation increment

### Legacy assignment regression fix

`services/assignment_summary.py` rolls up active responses without automatically
replacing a current primary. Additional offers or a different team's decline
preserve an accepted primary and its en-route/on-scene progress. With no active
response, remaining pending offers stay dispatched; with none, the case returns
to awaiting_dispatch. Closed cases reject new offers/responses. Repeated matching
answers are idempotent; changing an already answered offer into a withdrawal needs
a separate explicit workflow. Accepted legacy rows are not silently relabeled
as network supporting organizations.

The console also has a direct incident-status PATCH that still accepts a client-supplied
responder ID; securing only offer responses would leave an operational bypass.
It must be replaced/guarded during the authenticated adapter rollout.

This corrects sequential legacy behavior. It does not provide verified actor
ownership, lead/support authorization, case revisions or concurrent reassignment
protection. Those remain integration requirements.

### Pure permission policy

`access/policy.py` implements a deny-by-default policy over server-verified
principal and case snapshots:

- NOAA: verified organization membership, submitted reports across states,
  including geography needing review. No implied operational override/contact.
- Center coordinator: approved case-state scope for submitted professional
  reports, including other centers' cases. Active participation required for
  operational updates/contact. Lead coordinator alone can change responsibilities
  under the initial policy.
- Field rescuer: verified organization participation plus an accepted individual
  assignment and approved geography. No state-wide field-staff case feed.
- Reporter: own-report visibility and own active reporter availability updates.
  A person who also works for a center retains their own minimal reporter view.
- Volunteer: opt-in/role alone never grants professional access. A separate
  invitation/task-scoped view is still needed for accepted volunteer tasks.
- My-center includes lead, accepted support and confirmed receiving participation;
  pending offers/recommended destinations do not automatically grant involvement.
- Phone/text contact checks both operational involvement and that channel's
  current-case permission. Future-outreach consent is a separate purpose.
- Disabled/unverified identities, revoked memberships, unknown geography and
  out-of-state access fail closed for center professional records. Filters only
  narrow authorized visibility, never enlarge it.

**This module is not authentication and is not yet wired into legacy HTTP routes.**
Principals and case snapshots must come from verified sessions and persisted
membership/assignment/geography/consent, not request bodies, role pickers or
unsigned headers. No real NOAA/center user was provisioned in this increment.
The app must not be described as role-protected until all adapters are integrated.

### Minimal reporter projection

`access/reporter_view.py` enumerates an own-report response: case ID, verified
response phase/message, a fresh optional en-route arrival estimate, and voluntary
stay/leave semantics. No staff identity, coordinates, reporter phone, transcripts
or internal case fields are carried through. It distinguishes acceptance, travel,
arrival, animal located and closure. Phase must come from confirmed events, not
an image model. Stale/future/invalid estimates are unavailable; unknown does not
turn into zero. ETA source is explicit (manual, route estimate, rough distance).

This is an independently tested contract, not a new live ETA endpoint. Existing
reporter tracking and ETA routes have not been switched to it yet.

## Next integration sequence

1. Choose/verify sign-in and account provisioning (no existing app auth provider
   configuration was found in the inspected dependency/deployment files); map stable verified user IDs to
   active organizations/roles and approved state scopes. Never grant NOAA privilege
   from a self-entered role or email suffix alone. Account provider remains open.
2. Migrate membership, geography, participation and current-report ownership data.
   Preserve old assignments as legacy evidence; unverified state/ownership should
   not be auto-guessed into permission. Define receiving-center acceptance and
   cross-state exceptions with partners.
3. Add authenticated adapters enforcing the policy on every report surface:
   list/detail/media/transcript/history/related cases/counts/exports, coordination
   tools and all mutations. Return minimal reporter updates through a scoped
   account/tracking credential; retire the raw reporter-coordinate endpoint.
4. Replace hardcoded front-end identity, add role defaults and professional filters,
   field assigned-case/contact actions and the minimal reporter status screen.
5. Add explicit case participation/help requests, confirmed animal-located events,
   reporter availability, contact/consent records and notifications with acceptance,
   revocation/freshness checks and delivery audit.
6. Add saved-area volunteer invitations before optional background location. Test
   actual devices before promising continuous tracking. Keep drone test evidence
   separate from live incident/volunteer operations.

## Validation gates

Policy tests cover NOAA/global versus state views, ownership, unverified/revoked
memberships, geography uncertainty, lead/support/receiving filters, staff assignment,
contact channels, voluntary departure, minimal reporter data and ETA freshness.
HTTP regression tests use disposable fictional teams to check multi-offer/response
behavior, idempotence, preserved primary progress and closed-case protection.
No production DB migration, sign-in integration or outbound messaging is included.


GCP validation: 472 full offline backend tests passed, including 40 new
policy/projection/assignment regressions. Initial focused run: 65 passed before
the extra long-ETA check. Python lint and diff checks passed. One existing
Starlette/httpx dependency warning remains. No UI or live authorization rollout
was performed in this increment.
