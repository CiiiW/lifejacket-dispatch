# Reporter participation and nearby volunteer alerts

Status: requirements/design recorded, not implemented. Charlotte requested an
optional phone/text contact preference for future animal monitoring or rescue
support, plus opt-in location-based invitations for nearby volunteers.

## Separate the choices

Every reporter should have an opportunity to participate, while reporting remains
available without future-contact, volunteering or background-location consent.
All optional choices start off; do not infer agreement from filing a report.

| Choice | Meaning |
| --- | --- |
| Monitoring follow-up | May contact the reporter later about the reported animal or related monitoring task |
| Future rescue support | May invite the person to suitable future volunteer opportunities |
| Contact channels | Phone call, text message, or both; only use channels selected for the relevant purpose |
| Nearby notifications | May send suitable nearby task invitations through separately enabled notification channels |
| Location mode | Chosen area/radius, current location while using the app, or optional background sharing when the device/app supports it |

Keep current-report callback permission distinct from future outreach and nearby
volunteering. Record purposes and channels explicitly. Verify contact ownership
before enabling ongoing phone/text outreach. Notification delivery permissions
and device tokens are separate from agreeing to volunteer.

Background sharing is optional and requires explicit device permission plus
actual device validation. Do not promise reliable always-on location before that
work is tested. A saved area and radius should allow participation without
continuous tracking. State clearly when location was last updated and allow users
to pause availability, alerts or sharing independently.

## Reporter/volunteer record

Use a reusable participant profile linked to reports, rather than treating each
incident's phone number as a blanket subscription:

- Authenticated/profile identity and verified contact methods, linked report IDs.
- Contact preference and purpose/channel consents; current effective settings
  plus append-only consent events (notice version, granted/withdrawn time and source).
- Volunteer availability, chosen area/radius, supported task interests and any
  verified training/approval status. Opt-in alone does not establish qualifications.
- Location mode and explicit permission status; latest allowed position with
  timestamp/accuracy/expiry. Precise movement history is not required for matching.
- Notification subscriptions/devices and delivery outcomes, separated from contact
  details. Pause/revocation must be checked again before sending queued invitations.
- Task invitations, acceptance/decline/expiry and organization/case attribution.

Report/animal location is not automatically the reporter's current location.
Do not reuse an old sighting coordinate to claim that a volunteer is nearby.
For background/current-location matching, use only sufficiently fresh, permitted
positions. Saved-area matching must be labeled as chosen-area availability.
Define retention and deletion/account controls before collecting live history.

## Coordination workflow

1. A permitted rescue-center coordinator creates a case-linked help request with
   task type, location/area, time window, required qualifications and desired help.
2. Match opted-in, available people by approved area/radius, fresh allowed location
   where applicable, task suitability and notification/contact permissions.
3. Send a limited invitation; show what help is needed and ask the person to accept.
   An invitation is not an assignment and a notification is not proof of receipt.
4. The coordinator confirms accepted support and gives the appropriate briefing.
   Observation/update tasks and tasks requiring approved rescue personnel have
   different eligibility. Do not automatically dispatch an unapproved reporter.
5. Record acceptance, updates and completion on the shared case activity history.

A volunteer sees their own report, invitations and accepted-task information;
volunteer opt-in does not grant the professional statewide case view. Show only
information needed at each step. Participant phone numbers and precise live
locations are not a public directory or part of a statewide volunteer map.
Define who may contact a participant when a center requests assistance from
another center's network, with appropriate attribution and shared-case permissions.

## Withdrawal and delivery behavior

Provide profile controls for contact purposes/channels, availability, radius,
notifications and location sharing. Honor withdrawal for future outreach and
queued invitations; do not silently keep using an old location after sharing is
paused. Keep a minimal audit of consent changes separate from active permission.
Existing rescue/case records need their own retention rules; do not imply toggling
an opt-out deletes the historical case or un-sends an earlier message.

## Implementation stages

1. Build verified participant identity/contact ownership, preference forms,
   versioned consent records and access rules. Existing incident callback phones
   are not migrated into future-outreach opt-ins.
2. Add a coordinator-reviewed invitation workflow using opted-in saved areas and
   radii, with acceptance/decline/expiry and eligible task roles.
3. Add optional current/background-location subscriptions and push delivery after
   device permission, battery/freshness and pause/withdrawal behavior are validated.
4. Enable phone/text delivery only after provider setup and channel-specific consent,
   suppression, queued-delivery checks and audit behavior are implemented.

Current intake stores an optional `reporter_phone` and callback contact endpoint.
It does not provide this participant database, future-contact consent, volunteer
matching, background sharing or outbound alert delivery. No invitations/messages
were sent while recording this design.
