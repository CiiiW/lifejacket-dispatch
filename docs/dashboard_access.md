# Dashboard access and cross-center collaboration

Status: requirements/design recorded, not implemented. Based on Charlotte's
requested NOAA-wide and state-wide rescue-center visibility.

## Visibility and filters

| Account role | Authorized report scope | Default view | Optional filters |
| --- | --- | --- | --- |
| NOAA oversight | All submitted reports in the system, across states | All active reports | State, center, severity, animal group, case status, involvement |
| Rescue-center member | Submitted reports located in the organization's authorized state(s), including reports handled by other centers | Active reports in authorized state(s) | My center's cases, assigned to me, leading/supporting, help requested, nearby, severity, animal group, case status |

These are the requested product access rules, not a claim about external NOAA
operating policy. Current incident intake remains California-scoped; this design
does not itself expand supported reporting geography.

A center's authorized states come from verified organization membership and
admin-approved scope, not a state selector or the center's street address.
Filters narrow that scope. State membership must come from the report location
with recorded provenance; free-text place names alone are not an access boundary.
Unknown/unverified state stays in a NOAA/admin location-review queue until resolved.
Support multiple approved states for centers that work across state boundaries.

"All" includes reports available to that role, with active/closed status filters;
it does not mean deleting or losing archived reports. Unsubmitted intake drafts
need a separate visibility decision before inclusion.

## Distinguish responsibility, assistance and destination

Each case needs:

- **Lead organization:** accountable for coordinating the case.
- **Supporting organizations:** accepted participation, potentially several centers.
- **Assigned people/teams:** individual field responsibilities within participating organizations.
- **Receiving center:** intended animal destination; may differ from the lead.

Example: center A is the receiving center, while a nearby team from center B
assists with assessment, collection or transport. B's involvement is recorded
without overwriting A's receiving-center designation or silently transferring lead.
State-wide browsing alone does not assign a case or permit changing another
center's lead/destination. Request help, offer assistance and accept participation
must be explicit, logged actions. Changes to lead/destination need a recorded
coordinator decision. NOAA's write/override powers remain to be specified; global
visibility does not automatically grant unrestricted operational changes.

## Dashboard behavior

- Default state-wide view lets centers see nearby reports even when another
  center is responsible. A prominent **My center's cases** filter includes both
  lead and accepted supporting involvement.
- **Assigned to me** is a separate filter for individual staff/team assignments.
- Case cards/maps show lead, supporting centers, receiving center, status and
  whether help is requested. Cases merely viewed or offered but not accepted do
  not automatically become "my center's cases"; pending requests have their own view.
- Nearby filtering uses a selected incident or an explicitly supplied team
  position. Do not infer a team's current location from its center's base address.
- Combining map/list/status/species filters preserves the same authorized scope.

## Current implementation gaps

`clients/responder_console/App.tsx` hardcodes `RESPONDER_ID`.
`IncidentRow.assigned_responder_id` represents one assigned responder.
`AssignmentRow` retains offers/responses; it does not currently establish the
lead/support/receiving-center distinctions above. `ResponderRow.response_area`
is free text, and incidents have coordinates/place names but no normalized,
verified state scope. The current report list is not role-authorized.

## Implementation order

1. Select/verify the sign-in mechanism and map authenticated user identities to
   organizations, roles and approved state scopes. Derive the acting identity on
   the server; replace client-supplied/hardcoded identities as authorization inputs.
2. Add normalized incident geography and explicit organization participation,
   lead/destination fields and person/team assignments through a migration that
   preserves current records and their meaning. Do not reinterpret old offers as
   accepted supporting participation.
3. Enforce role/state visibility in the backend before exposing the controls.
   Apply it to lists, detail, photos, transcripts, search, counts, exports and
   related-case references. Direct URLs must obey the same policy as the map.
4. Add auditable help requests, offers, acceptance/withdrawal and permissions for
   changing case responsibilities. Support should not accidentally claim/close
   the case or replace the receiving center.
5. Add dashboard filters and role-appropriate defaults using the server's verified
   identity/scope. A role picker alone is only a labeled demo, not authentication.
6. Test NOAA-wide access, same-state cross-center browsing, out-of-state denial,
   missing state, multi-state scope, accepted lead/support involvement, individual
   assignments, revoked memberships and direct-link/export access.

Not yet decided: sign-in provider, account provisioning/admin ownership,
NOAA operational write permissions and cross-state assistance exceptions.
These decisions do not prevent building the data model/policy tests, but actual
access enforcement must be verified across all report surfaces before claiming RBAC.

## Network model: two-way coordination

Charlotte clarified that LifeJacket should connect reporter ↔ rescue center,
center ↔ center, and center ↔ NOAA. It is a proposed shared coordination network,
not only a report-routing service. This is product intent; no external NOAA or
center system integration/operating agreement is claimed.

The case is the shared workspace and activity record:

| Connection | Initial interactions |
| --- | --- |
| Reporter ↔ case team | Submit evidence/location, answer follow-up questions, receive appropriate status updates |
| Center ↔ center | Request/offer help, accept support, coordinate field response/transport, propose handoff and share availability |
| Center → NOAA | Case status, unresolved questions, resource gaps, requests for guidance |
| NOAA → centers | Request information/review, publish case-linked guidance/advisories and acknowledge updates |

NOAA coordination and operational decision powers still require explicit product
permissions and partner input; oversight visibility alone is not automatic command
authority. Reporter views remain limited to their own report and appropriate
updates, not the statewide professional workspace.

Use typed, case-linked events for help requests, offers, acceptance, updates,
information requests, guidance, acknowledgements and handoff decisions. Record
organization/person attribution, timestamps, revisions and action status. Keep
receiving-center, case-lead and accepted-support changes explicit and auditable.
An in-app request does not imply an email/SMS was sent or that a team accepted.

Views of the shared record follow the same role/state/participation policy:
state-wide professional discovery, my-center and assigned-to-me views, and NOAA's
global oversight. Define the authorized audience for case activities/documents
as well as the report itself. Filters must not expand access.

MVP sequence: verified identity/scopes → shared case activity → help request/offer/
acceptance between centers → NOAA information/guidance exchange → handoff and
availability refinements. Delivery channels and external integrations can follow
once in-app permissions, acknowledgements and audit behavior are reliable.


## Reporter participation

See [reporter participation design](reporter_participation.md) for optional
monitoring/future-support contact preferences, verified participant profiles,
versioned consent, nearby invitations and optional location sharing. Volunteer
participation does not grant a center's statewide professional access.
