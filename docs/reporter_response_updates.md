# Assigned rescuers and reporter response updates

Status: requirements/design recorded, not a completed permission or notification
implementation. Complements the access and reporter-participation designs.

## Rescuer workflow

- Field rescuers get **Assigned to me**: cases/tasks they have accepted or are
  actively assigned to. Center coordinators retain the state-wide discovery view
  and **My center's cases** for lead/accepted-support participation.
- From an active assigned case, an authorized rescuer can contact the reporter
  through a provided, permitted phone/text channel to clarify location, access,
  animal movement or meeting arrangements. Contact should be usable en route;
  the app does not require interacting while driving.
- Reporter contact details are case-scoped and available to authorized involved
  staff who need them, not to every center browsing the state-wide map or the
  public. Revoked/unrelated assignments do not retain operational contact access.
- Calling/texting about this report is distinct from future monitoring contact
  and nearby-volunteer subscriptions. Honor each purpose/channel preference.
- Record operational status and relevant case activity; do not claim a call/text
  was delivered or received merely because the user opened a contact action.

## Minimal reporter-facing timeline

| Verified event | Reporter update |
| --- | --- |
| Report submitted, no accepted response yet | Report received; awaiting team confirmation |
| Team accepts responsibility | A team has taken your report |
| Team actually departs / marks en route | Team is on the way; approximate arrival if available |
| Team arrives at the location | Team has arrived and is checking the area |
| Team confirms the animal is located | The team has located the animal |
| Coordinator/rescuer records a shareable outcome | Case update or closure appropriate for the reporter |

An offer/suggested center does not mean the case was accepted. Acceptance does
not by itself mean travel has begun. Arrival at the scene does not mean the
animal was found, and animal found does not mean rescue/closure is complete.
Make animal-located confirmation a separate event/field from on-scene status.
Use manual responder confirmation, not AI inference, for that event.

Reporter updates are available only for the reporter's own report through an
appropriate account or securely scoped tracking credential. Publicly knowing
an incident ID must not grant contact details, professional notes or tracking.

## ETA behavior

ETA is an estimate of **arrival**, not a promise of when a case will be resolved.
Display an approximate time/range, its last update and when it is unavailable.
Only active en-route responders produce a travel ETA; accepted-but-not-departed
cases show team confirmation without implying movement. On-scene cases show
arrival, not a remaining drive time. Handle delays, withdrawals/reassignment,
stale location and connection loss rather than continuing a misleading countdown.

The reporter does not need live responder coordinates, a moving team map, staff
personal details, internal conversations or the statewide case feed. Keep the
professional map/team positions within its own permissions. A reporter-specific
API response must omit unnecessary internal fields rather than only hiding UI.
Notification messages should contain minimal own-case updates and open the
scoped report view. Push/SMS delivery preferences apply independently.

## Reporter presence is optional

For a short ETA, offer the reporter a choice to remain nearby if they wish, with
existing wildlife-distance guidance. Make equally clear that they may leave at
any time; leaving does not cancel the report or forfeit the team's response.
Do not require a reporter to remain until arrival, touch/handle an animal or
confirm rescue success.

Possible choices: still nearby, leaving/already left, available for a callback.
If leaving, allow optional last-seen time, updated animal location, landmarks or
safe-access notes. Tell the assigned team about the reporter's availability as
case activity. Do not assume a reporter stays because their location was shared,
and do not move the animal marker when the reporter leaves. Offer the same
status/animal-located updates after departure through enabled channels.

## Existing code and missing work

- `AssignmentStatus` already includes accepted, en_route and on_scene.
- `responders.py` exposes an ETA endpoint for active assignments using a distance-
  based drive estimate. It returns responder coordinates and includes accepted/
  on-scene assignments; that is not yet this minimal reporter status contract.
- Reporter `TrackScreen` displays approximate ETAs and responder map markers;
  the new requirement should replace that detail with scoped status/arrival views.
- Reporter callback phone storage exists, but verified identity, case-scoped
  contact permission/channel actions and future-consent separation need work.
- Add reporter availability/last-seen updates, animal-located confirmation,
  subscriber notification preferences and honest ETA freshness/source handling.

## Acceptance checks

Test own-report access and unrelated-report denial; assigned rescuer contact and
revoked/unrelated access denial; lead/support participation; current-report vs
future-contact preferences; no ETA before departure; arrival vs animal-found vs
closure; stale/unavailable ETA; reporter departure without report cancellation;
minimal reporter payload without responder coordinates/internal records; and
updates reaching only opted-in/report-authorized recipients.


A minimal reporter projection and authorization policy are now implemented as
pure backend functions; [audit and integration plan](network_implementation_audit.md).
The legacy reporter screen/ETA endpoint are not yet using that contract.
