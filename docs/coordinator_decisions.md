# Coordinator decisions, volunteers and the reporter thread

Status: implemented in the **local console** (legacy mode) only. Every route
below is a legacy route, so network mode's allowlist boundary blocks all of
them (`test_every_new_route_is_blocked_in_network_mode`). Nothing here is a
signed-in, role-checked workflow; see `dashboard_access.md` for that design.

## Four decisions per incident

The incident screen ends with a **Decide** card, after the photo, the
conditions, the summary and the rest of the report, so the case is read
before anything is decided. One option is marked
*suggested* from the triage band (critical/respond → team, monitor →
volunteers, guidance → ignore). It is a suggestion; options can be combined.

| Decision | What it does | Recorded as |
| --- | --- | --- |
| Ignore | Closes the case with a reason. "Healthy animal" → `guidance_only`; any other reason → `cancelled`. Refused once a team has accepted. Alerts still awaiting a reply are stood down; volunteers who already checked in are **not** told automatically. | `coordinator_ignored` event |
| Send a team | The existing `POST /responders/assign` offer to a suggested centre. An offer is not an acceptance; the coordinator records the team's answer. | existing `assignment_offered` / `assignment_response` |
| Send volunteers | Alerts nearby volunteers to check in (below). | `volunteers_alerted`, `volunteer_reply` |
| Send a drone | Plans a survey grid over the animal with the existing planner and its server-side limits. Launch point assumed 120 m east (landward on the California coast). **Simulation only**: nothing commands an aircraft. California only, like the planner. | `drone_survey_planned` |

The card's decision log reads these events. Event details never contain
message or alert text, because incident events reach the coordination agent's
prompt as observations.

## Volunteers

`data/seeds/demo_volunteers.json` holds 25 **fictional** volunteers (17 around
Monterey Bay, 8 elsewhere in California): invented names, 555-0100..0199
numbers (reserved for fiction), street-level addresses with no house numbers,
geocoded once with Nominatim. Load them with `POST /volunteers/seed-demo` or
the console's button. They live in their own `volunteers` table, not
`responders`, so they never reach dispatch ranking or the coordination agent's
`get_available_responders` tool.

Rules, from `reporter_participation.md`:

- **An alert is an invitation, not an assignment**, and `delivery` is always
  `simulated`: no SMS provider exists, and no text is ever sent. A reply is
  recorded explicitly by whoever received it (`POST /volunteers/alerts/{id}/reply`).
- **Task follows the triage band.** Monitor/guidance → *observe* (any
  volunteer). Respond/critical → *support a team* (trained responders only),
  never instead of one.
- **Eligibility:** available (not paused), within the volunteer's own travel
  radius, and qualified for the task. The API refuses an ineligible alert and
  sends none of a batch that contains one.
- **No statewide volunteer map.** There is no list-all endpoint; the console
  only sees volunteers within 60 km of the selected incident. Positions are
  base areas, labelled as such, not live locations. Phone numbers never leave
  the server (last four digits only).

## Coordinator ↔ reporter thread

A coordinator and the person who filed a report can message each other. The
reporter uses the app's **Communications** tab (one conversation per report,
signed "Rescue team" on the team's side); the console has a **Communications**
tab too, listing every reachable reporter with the threads owed a reply on top
and counted in the tab label, as well as the thread on each incident page.
Using the app means sharing a phone number with the rescue organisation: it is
asked for once, on first launch, and sent with every report.

- Incident IDs are 8 hex characters read aloud over radios, so they are not
  secrets. `/intake/start` therefore issues a **per-report key** (returned once,
  stored as a SHA-256). The reporter routes require it in `X-Reporter-Key`;
  every failure returns the same 403, so the API does not reveal which
  incidents exist.
- The reporter's view is text, direction and time: never the coordinator's
  identity, notes or anyone's contact details.
- Either side may write first, so a reporter can say "it moved into the
  water" without being asked. Reports from before messaging existed, or not
  from the reporter app, have no key; the console leaves them out of
  Communications and the incident page leaves out the message card, instead
  of offering a box nobody can read.
- Messages live in `incident_messages`, separate from `chat_messages` (the
  agents' transcript, which is fed back into their prompts).
- The open thread polls every 4 s on both sides; the console's inbox every
  10 s, the app's report summaries every 15 s (`POST /intake/my-reports`,
  keys in the body). The app saves each report's key on the phone
  (`src/lib/reporterStore.ts`, a JSON file in its documents folder), so My
  reports and the conversations survive a restart. Deleting the app loses
  them; the reports themselves stay with the rescue network.

## API

| Route | Purpose |
| --- | --- |
| `GET /incidents/{id}/volunteers` | Volunteers within 60 km, eligibility, latest alert |
| `GET`/`POST /incidents/{id}/volunteer-alerts` | List / send alerts |
| `POST /volunteers/alerts/{id}/reply` | Record `checked_in` or `declined` |
| `GET /volunteers/summary`, `POST /volunteers/seed-demo` | Roster counts / load the fictional roster |
| `POST /incidents/{id}/ignore` | Close with a reason |
| `POST /incidents/{id}/drone-survey` | Plan a simulated survey |
| `GET /incidents/{id}/decisions` | Decision log |
| `GET`/`POST /incidents/{id}/messages` | Coordinator side of the thread |
| `GET`/`POST /intake/{id}/messages` | Reporter side; needs `X-Reporter-Key` |
| `GET /communications/threads` | Console inbox: every reachable reporter, replies owed first |
| `POST /intake/my-reports` | The app's My reports: status and thread summary per key held |
| `GET /intake/{id}/progress` | Which intake step is running, for the app's waiting line; needs the key |

Code: `backend/lifejacket/services/{volunteers,reporter_thread,coordinator_actions}.py`,
`backend/lifejacket/services/progress.py`,
`backend/lifejacket/api/routes/{coordinator_actions,volunteers,reporter_thread,communications}.py`,
`backend/tests/{test_coordinator_actions,test_reporter_communications}.py`; console
`src/components/{DecisionPanel,VolunteerPanel,VolunteerMap,ReporterChat}.tsx`,
`src/screens/CommunicationsScreen.tsx`; reporter
`src/screens/{CommunicationsScreen,MyReportsScreen,PhoneSetupScreen}.tsx`,
`src/lib/{reporterStore,useMyReports,useTeamThread}.ts`.

## Not done

Real SMS delivery and volunteer-side replies (needs a provider, consent and
suppression handling per `reporter_participation.md`); telling checked-in
volunteers that a case closed; push notifications for new messages (the app
polls while open); per-person attribution (the console still uses the hardcoded
`RESPONDER_ID`); network-mode equivalents.
