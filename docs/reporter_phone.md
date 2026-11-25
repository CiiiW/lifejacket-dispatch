# Phone-verified reporter flow

Live SMS and a production deployment remain pending.

## Reporter experience

The browser entry (`clients/reporter_app/App.web.tsx`) opens a phone-friendly chat.
Reporters can share a camera or library photo, choose the animal in the image,
confirm the animal's location using GPS or a map pin, and reply to follow-up
questions in the same conversation. They can prepare a draft without an account,
verify a phone through the managed SMS SDK, then explicitly submit. Verification
alone does not submit a report. No password or blanket future-outreach consent
is required. Call/text choices apply only to this case and default off.

The reporter can sign in again and load their own submitted cases. The status view
shows the reported animal location, current contact choices, and the name of a
verified response team after acceptance. It omits staff positions, private
contacts, staff notes and other cases.
Leaving records availability without changing case status or cancelling it.
No ETA is invented: the current route has no reviewed arrival source, so it
returns unavailable. Reviewed case phases can distinguish acceptance, travel,
arrival, animal located and closure. No SMS/push case-update delivery exists yet;
status is checked in the app every 30 seconds or on explicit refresh.

Draft keys live only in page memory, expire after 24 hours, and are stored as
SHA-256 hashes server-side. Reloading loses the private draft key. Expiry denies
access; it is not a deletion/retention policy. Submitted report history is tied
to the verified provider issuer/subject, not a typed phone number. Reassignment
of a phone number to another provider subject does not transfer historical cases.

## Security boundary

- Both `NETWORK_AUTH_ENABLED=true` and `REPORTER_PHONE_ENABLED=true` are required.
  Both defaults preserve the existing private demos and fail closed for the new API.
- The network middleware allows only enumerated reporter POST routes and continues
  blocking legacy intake, incident/photo, responder ETA and mutation endpoints.
- Draft readiness creates no `network_cases` enrollment. Explicit submission requires
  a valid draft key, completed conversation and server-verified managed phone ID token.
  A client `phone_verified` boolean or typed contact number is never trusted.
- Verification retains the existing signature/issuer/audience/expiry, revocation and
  disabled-user checks. Submission additionally requires phone sign-in and auth time
  within 15 minutes. Professional roles still require approved DB memberships and
  verified email; phone verification creates no professional role.
- Credentials use POST bodies, never URL parameters or shareable tracking links.
  This dedicated reporter transport accommodates the previously observed notebook
  proxy header limitation without changing professional bearer-token verification.
  Live proxy behavior still needs an end-to-end user sign-in test.
- Submitted reads and presence updates check current local account enabled state,
  explicit ownership, and current submitted metadata on every call. No raw media URL
  or unrelated case data is returned. Case-state advancement needs reviewed metadata.
- Only current-case contact permissions are recorded (`current-case-v1`). The phone
  is kept in the private reporter row, not copied into legacy free-form phone storage.
  There is no legacy call-button fallback that can ignore a text-only preference.
  A permission-checked professional contact endpoint is a separate pending step.
- Responses are private/no-store; request validation does not echo credentials or
  report content. Do not enable request-body logging at a gateway or error tracker.
  The SDK uses in-memory auth persistence; the application stores no passwords/OTP codes.

## Setup before live use

1. Owner grants the already prepared minimal `firebaseauth.users.get` role to the
   Workbench service account. Current project Editor cannot grant it; no broader
   permission is substituted and revocation checks stay on.
2. Configure Phone in Identity Platform, SMS billing/region policy, quotas and abuse
   controls, and the approved public HTTPS application domain. No SMS provider or
   billing setting was activated by this change; no SMS was sent.
3. Supply the reporter's public Firebase config and `EXPO_PUBLIC_REPORTER_PHONE_ENABLED=true`.
   Use the same managed auth project expected by backend `FIREBASE_AUTH_PROJECT_ID`.
   Never put a service-account key in the client. Lock backend CORS to approved origins.
4. Before any public launch, put request/body/upload limits and rate limits on draft
   creation, uploads and model-backed turns; validate request-body redaction and review
   retention/deletion rules. Feature flags remain off during this implementation.
5. Run a real user-controlled SMS/reCAPTCHA check on the approved domain, submit a
   disposable case in an isolated DB, reauthenticate, and check own-case isolation.
   Fictional UI tests cannot establish actual SMS delivery or live proxy compatibility.

The browser SDK displays the provider security challenge. Real users complete it;
no app-verification bypass or production testing codes are enabled. The consent
text discloses verification SMS/standard rates and Google's number processing.
Sources: https://firebase.google.com/docs/auth/web/phone-auth .

## Native app

With an approved HTTPS `EXPO_PUBLIC_REPORTER_WEB_URL` configured, the native
wrapper opens the phone-browser flow and does not fall back to unverified intake.

Without one — local development and Expo Go — it shows the reporter console
(Report / My reports / Communications) instead, so the app is testable on a
phone. It asks for the reporter's number once, on first launch (using the app
shares it with the rescue organisation), and keeps every report on the phone so
another can be filed without restarting. That path
submits through the legacy intake API and is **not phone-verified**; it carries a
banner on screen saying so. `EXPO_PUBLIC_LEGACY_REPORTER_DEMO=true` forces the
console even when a web URL is set, for checking a deployment build locally.

For screen recordings, `EXPO_PUBLIC_DEMO_MODE=true` keeps the phone's real
position off camera: **Share location** opens the map on Jetty Beach, Moss
Landing (real coastal tide data) instead of reading GPS, and the banner is
hidden. The spot is sent as a `map_pin`, not `device_gps`. Restart with
`npx expo start -c` after changing it. See `clients/reporter_app/src/lib/demo.ts`.

Native SMS support requires a development build plus the native
Firebase/APNs/app-verification setup; Expo Go does not include those native
modules, so there is no verified native path to fall back to. No native-device
verification is claimed.
Source: https://rnfirebase.io/ .

## Tests and fixture

Backend tests cover draft secrecy/expiry, completion before submission, invalid,
stale and non-phone identities, spoofed verification, disabled accounts, idempotent
submission, unrelated-subject denial, minimal status, reviewed phases, leaving without
cancellation, managed revocation checks, redacted validation and the legacy-route boundary.

`clients/reporter_app/tests/phoneReporterPreview.tsx` injects a fictional API and phone
auth driver, never imported by the app. It sends no API, SMS, login or rescue request.
The separate static fixture can test failed codes, unavailable-provider handling,
submission gates, receipt tracking and unavailable status. The fictional six-digit
code exists only in that fixture; production has no such code or bypass.

Validation: full backend regression suite passed; four reporter API transport tests passed; reporter TypeScript check and web export passed. Fictional browser checks passed for provider unavailable, unverified submission gate, failed code with code clearing, verified submission, own receipt history, animal-located status, departure without cancellation, unavailable-status clearing, and sign-out cleanup. These do not establish live SMS delivery or native-device support.

Current-case contact permission can now be withdrawn from the own-case screen without
cancelling the report. Assigned/involved staff contact and confirmed response events
are implemented behind a separate default-off operational flag; see `rescuer_response_flow.md`.
