# Clients

Two apps, both Expo SDK 57 (React Native 0.86) + TypeScript.

Keep both on the SDK that Expo Go currently ships: Expo Go supports only the
latest SDK, so falling behind means the reporter app cannot be run on an
iPhone without a paid Apple Developer account.

| App | Audience | Platforms | Entry point |
|---|---|---|---|
| [`reporter_app/`](reporter_app/) | The public | iOS, Android | Report an animal, chat with the agent, watch help arrive |
| [`responder_console/`](responder_console/) | Rescue organisations | iOS, Android, **web** | Triage map, navigate to incidents, log outcomes |

## Why Expo for both

The specification calls for the reporter app to be phone-only and the responder
console to work on **both phone and web**. Expo compiles the same React Native
codebase to iOS, Android, and the browser (via `react-native-web`), so the
console is one codebase rather than a native app plus a separate React site.

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

Both need the backend up first:

```bash
# from the repository root
uvicorn lifejacket.api.main:app --reload --app-dir backend
```

Then:

```bash
cd clients/reporter_app      # or responder_console
npm install
npx expo start               # press i for iOS, a for Android, w for web
```

On a physical device, `localhost` points at the phone, not your laptop. Set the
API base URL to your machine's LAN address:

```bash
EXPO_PUBLIC_API_URL=http://192.168.1.42:8000 npx expo start
```

## Status

These are working scaffolds, not finished apps: the screens and API wiring are
real and styled to the design system above, but there is no authentication yet
(`RESPONDER_ID` is hardcoded in the console's `App.tsx`). See the repository
README's "Where to pick up" section.

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
