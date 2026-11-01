# Clients

Two apps, both Expo SDK 57 (React Native 0.86) + TypeScript.

The reporter's phone-verified flow currently runs in the browser (including
mobile Safari). Its default native wrapper links to the configured web app;
native SMS support requires a development build. The old native reporter is
an explicit private demo, not a verified production fallback.

| App | Audience | Current entry |
| --- | --- | --- |
| [`reporter_app/`](reporter_app/) | Reporters | Phone-browser draft, SMS verification, own-case status |
| [`responder_console/`](responder_console/) | NOAA/centers/rescuers | Web role-scoped cases and confirmed response actions |

For a no-credentials VS Code demo, start at the repository root with `npm ci`,
`npm run setup:demos`, then `npm run demo:network`. See
[teammate setup](../docs/teammate_setup.md). This does not require a running API.

## The rule these apps follow

**No decision logic in the clients.** They render what the backend tells them
and send back what the user does. Species identification, severity triage,
duplicate detection, and responder ranking all live in Python, so that:

- there is one implementation to test and evaluate, not three;
- a scoring change ships without an app-store review;
- the research notebooks exercise exactly the code the apps use.

In practice this means a client never computes a severity colour from flags --
it reads `severity_level` off the response. If you find yourself wanting a
condition flag in order to decide something, add it to the API instead.

## Design system

`shared/theme.ts` holds the palette, radii, type scale, and shadow both apps
use: deep ocean navy ground (`#0B132B`), seafoam accent (`#48CAE4`) reserved
for active indicators and primary actions, translucent "glass" cards with
12px corners. Screens import tokens via `src/lib/theme.ts` rather than
hardcoding hex values, so a palette change lands in one file.

Two platform notes:

- The glass blur is a web-only CSS `backdropFilter`. Native degrades to the
  plain translucent fill, which still reads correctly, or add `expo-blur`.
- `severityColour` in `shared/api.ts` is tuned for the dark ground. It is the
  one place a backend value maps to a colour.

## Running them

The actual live clients need a configured backend first:

```bash
# from the repository root
uvicorn lifejacket.api.main:app --reload --app-dir backend
```

Then:

```bash
cd clients/reporter_app      # or responder_console
npm ci
npx expo start               # press i for iOS, a for Android, w for web
```

On a physical device, `localhost` points at the phone, not your laptop. Set the
API base URL to your machine's LAN address:

```bash
EXPO_PUBLIC_API_URL=http://192.168.1.42:8000 npx expo start
```

## Status

The new web network/phone flows implement managed sign-in, database-backed access
boundaries and confirmed case response actions. Live sign-in/SMS setup is still
pending. The older private console contains a hardcoded responder ID and must
not be confused with the verified network mode. See the setup docs linked above.

Incident detail includes an explicit Check Coordination action: it makes live
model calls and shows record-backed review proposals, never dispatches.
Handover retrieves recorded changes and current open cases without model
calls. See the [workflow map](../docs/rescue_workflows.md) and
[connected demo](../demo/connected_workflow.md). These new views typecheck,
but mobile/desktop visual QA is still outstanding.

## Maps

The two platforms draw maps with different libraries, because
`react-native-maps` has no web renderer and MapLibre's React Native binding
needs a custom dev client (so it cannot run in Expo Go).

| Platform | Library | File |
|---|---|---|
| Web | MapLibre GL JS | `src/components/TriageMap.web.tsx` |
| iOS / Android | `react-native-maps` | `src/screens/IncidentMapScreen.tsx` |

The web map draws three things: incidents coloured by backend-computed
severity, rescue centres as small rings, and a route between them.

**Tiles** come from MapTiler or Stadia if `EXPO_PUBLIC_MAPTILER_KEY` or
`EXPO_PUBLIC_STADIA_KEY` is set (see `.env.example`), and otherwise from
keyless OpenStreetMap raster tiles. The fallback works but is light against
the dark theme, and OSM's tile policy rules it out for production. A badge in
the map corner always says which is in use.

**Routes** come from OpenRouteService via the backend
(`GET /incidents/{id}/route`), never from the browser, so the routing key
stays server-side. With no key configured the backend returns a straight
line marked `source: "straight_line"`, and the map dashes it so it cannot be
mistaken for a drivable distance.

**Turn-by-turn** is deliberately not built here. The incident detail screen's
*Navigate* button deep-links to Google Maps (Apple Maps on iOS), which does
it better than we would.

Known gap: rescue-centre coordinates are *service-area centroids*, not street
addresses -- the directory has no addresses, so `POST /responders/geocode`
resolves the coverage prose instead. Good enough to see which stretch of
coast a centre covers; not good enough to drive to. 29 of 33 resolve.

Note `maplibre-gl` is pinned to v4: v6 uses `import.meta`, which Metro cannot
bundle. `babel.config.js` exists only to enable the static-class-block
transform that MapLibre needs.
