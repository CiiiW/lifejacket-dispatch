# Clients

Two apps, both Expo + React Native + TypeScript.

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
real, the styling is minimal, and there is no authentication yet. See the
repository README's "Where to pick up" section.
