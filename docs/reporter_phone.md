# Phone-verified reporter flow

Implemented on `charlotte-mini2-demo`; live SMS and deployment remain pending.

## Reporter experience

The browser entry (`clients/reporter_app/App.web.tsx`) works as a phone-friendly
reporter UI: prepare a photo/location/conversation draft without an account,
verify a phone through the managed SMS SDK, then explicitly submit. Verification
alone does not submit a report. No password or blanket future-outreach consent
is required. Call/text choices apply only to this case and default off.

The reporter can sign in again and load their own submitted cases. Status is a
minimal projection, with no staff positions, contacts, notes or statewide feed.
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

The default native wrapper does not fall back to unverified intake. Set an approved
HTTPS `EXPO_PUBLIC_REPORTER_WEB_URL` to open the phone-browser flow. The old native
screens remain available only with explicit `EXPO_PUBLIC_LEGACY_REPORTER_DEMO=true`
for private demos and are not phone-verified. Native SMS support requires a development
build plus the native Firebase/APNs/app-verification setup; Expo Go does not include
those native modules. No native-device verification is claimed.
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
