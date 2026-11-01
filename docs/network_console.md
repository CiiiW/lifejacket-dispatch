# Verified network web console

The responder console now has a Rescue network tab and a dedicated network-only build. It uses managed Google sign-in and server-approved organization contexts. The current private demo remains in legacy mode; this work has not activated a cloud provider, granted memberships, enrolled real reports or sent notifications.

## User experience

- Sign-in screen: Google sign-in when the web app configuration is present; otherwise a clear unavailable state. A missing configuration does not unlock a demo identity.
- Personal account: receipt case-ID lookup for the caller's own report, minimal status, optional estimated arrival when supplied, and explicit permission to leave without cancelling. No professional membership is created by sign-in.
- Professional context: select only organizations returned by the authenticated session endpoint. Show the backend's role and approved states, then list authorized cases with My center / Assigned to me / Leading / Supporting / Receiving filters. Detail requests recheck access; no legacy full-detail request is used.
- Cases clear on account/context changes and on denied/failed refresh. Pending requests are aborted or their late responses ignored. Access is rechecked every 30 seconds and when returning to the browser tab; displayed data may remain visible until that check. Server authorization still happens on every request.
- Sign-out immediately removes the case view. SDK identity persistence is in memory, so a full page reload requires signing in again. The app does not write ID/refresh tokens or case records to web storage.
- Read-only: no contact, dispatch, location tracking, handoff or rescue-status buttons are wired to legacy mutations. Native app sign-in is not implemented by this slice; the native tab directs users to the web console.

## Configuration

Use the responder console's `.env.example` for these public build-time values:

| Variable | Purpose |
| --- | --- |
| `EXPO_PUBLIC_NETWORK_MODE=true` | Render only the authenticated network console; no legacy navigation/fallback. |
| `EXPO_PUBLIC_API_URL` | HTTPS API origin plus optional proxy prefix; loopback HTTP is allowed for development. No username, password, query string or fragment. |
| `EXPO_PUBLIC_FIREBASE_API_KEY` | Firebase **web app** API key, not an Admin key. |
| `EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN` | Managed sign-in domain. |
| `EXPO_PUBLIC_FIREBASE_PROJECT_ID` | Same managed identity project expected by the backend verifier. |
| `EXPO_PUBLIC_FIREBASE_APP_ID` | Registered Firebase web app ID. |

The backend must have the intended provider/project configured, `NETWORK_AUTH_ENABLED=true`, reviewed access/case tables and appropriate CORS origins. Enabling backend network mode blocks all legacy routes. Coordinate the client build with this switch; do not enable it on the existing demo service mid-session.

Firebase/provider configuration and authorized domains are external setup steps, not created by npm installation or a build. No service-account credentials belong in `EXPO_PUBLIC_*`. Public web configuration does not grant NOAA or center access; the database membership approval process remains required. See [sign-in setup](network_signin.md) and [case read boundaries](network_case_access.md).

## Token transport and Workbench limitation

The real client sends `Authorization: Bearer <ID token>` and organization selection headers to the configured HTTPS API. The backend's managed cryptographic verifier and membership rules are unchanged. There is no trusted user/role header, anonymous fallback or query-string token. Fetch refuses redirects, obtains a current SDK token on each request and uses same-origin cookies only for an existing gateway. Cross-origin requests do not send gateway cookies. Token lookup and HTTP requests have a 15-second logical deadline; late token lookup results cannot send a cancelled request.

Browser fixture requests through this Workbench notebook proxy arrived without application authentication headers, including a separately tested dedicated token header. Direct loopback requests preserved them. The provider/API endpoint must be configured and verified on a domain that preserves app authentication headers before claiming live sign-in works. The client remains fail-closed through the notebook proxy. No proxy authentication protections were disabled and no weaker auth path was added.

## Verification and isolated preview

Run in `clients/responder_console` with a Node version that supports built-in TypeScript stripping (GCP currently uses Node 25):

```
node --test tests/networkApi.test.mjs
npm run typecheck
EXPO_PUBLIC_NETWORK_MODE=true npx expo export --platform web --output-dir dist-network
```

`tests/networkPreview.tsx` is a separate component-test entry point, never imported by the app. Build it with esbuild, defining `process.env` as `{}` and resolving modules from the console's node_modules; serve its generated index/app.js directory with `python scripts/serve_network_ui_fixture.py --web-dir <fixture directory>`. The server binds only to loopback and serves static files. Fictional identities, cases, organization changes and revocation controls are in the test component's memory. The fixture makes no API/sign-in requests, imports no application database and provides no production auth bypass. Browser component checks verify UI behavior; client transport tests and backend authorization tests verify their respective layers separately. This is not a live managed sign-in or proxy authentication test.

Remaining work: configure and test actual provider sign-in on the intended domain/devices; connect authenticated intake/ownership, reviewed evidence and contact consent; add permitted assignment/coordination and response-event workflows; native sign-in; map view and further case filters. The current UI does not claim these capabilities.

Official SDK references: [Google sign-in](https://firebase.google.com/docs/auth/web/google-signin), [Auth initialization](https://firebase.google.com/docs/reference/js/auth#initializeauth), [persistence](https://firebase.google.com/docs/auth/web/auth-state-persistence).

## Recorded validation

GCP: 10 client request tests; TypeScript check; network-only Expo web export;
Python lint/diff checks; final backend regression suite 537 passed with one
existing Starlette/httpx warning. Browser component checks verified CA versus
AK views, NOAA's broader view, detail, empty filters, personal report status and
unavailable cases, revocation and sign-out clearing during delayed results.
The final production build was opened separately and correctly showed missing
sign-in configuration with no legacy navigation. Live provider/API integration
was not exercised.

The image below is a fictional component fixture, not a live NOAA account or
real rescue reports.

![Fictional network console component check](evidence/network_console_fixture.png)
