# Data model

The entities, how they relate, and the one design compromise worth
understanding before you write a query.

Defined in:
- [`backend/lifejacket/models/schemas.py`](../backend/lifejacket/models/schemas.py) — Pydantic, the vocabulary every module speaks
- [`backend/lifejacket/models/tables.py`](../backend/lifejacket/models/tables.py) — SQLAlchemy, how it is stored
- [`backend/lifejacket/models/repository.py`](../backend/lifejacket/models/repository.py) — conversion between the two

## Entities

```
incidents ─┬─< photos              one reported animal, one row
           ├─< chat_messages       the full reporter conversation
           ├─< assignments >─ responders
           └─< incident_logs       the responder's closing write-up
```

| Table | What it holds |
|---|---|
| `incidents` | One reported animal, from first photo to responder sign-off. The central table. |
| `photos` | Metadata and a disk path. Image bytes are **not** in the database. |
| `chat_messages` | Every turn, reporter and agent. The project's richest research asset. |
| `responders` | Rescue organisations (seeded from `data/rescue_centers.csv`) and volunteers. |
| `assignments` | A responder being offered or taking an incident. Separate from `incidents.assigned_responder_id` so the offer history survives a decline. |
| `incident_logs` | What the animal actually turned out to be, and what happened. **The only ground truth in the system.** |

## The one compromise: promoted columns

The agents produce deeply nested objects — `AssessmentResult` contains an
`InjuryAssessment` containing ten booleans. Two obvious storage choices are
both wrong here:

- A column per leaf means a migration every time a prompt changes, which during
  a research project is weekly.
- One JSON blob makes the responder map impossible to query.

So **both**. Fields the application filters, sorts, or maps on are real
columns; the complete object is stored alongside as JSON.

```
incidents.severity_level      ← real column, indexed    (triage list sorts by it)
incidents.assessment_json     ← the full AssessmentResult
```

**The rule:** if a SQL `WHERE` clause needs it, promote it. Otherwise leave it
in JSON.

**Which is authoritative:** the JSON. `repository.save_incident` recomputes
every promoted column from the nested objects on each save, so they cannot
drift. `row_to_incident` reads from JSON, never from the promoted columns.

Promoted today: location, species name/confidence/group, `taxon_rank`,
severity level/score, `injury_present`, `entanglement_present`,
`report_headline`.

Note `species_common_name` holds the **resolved** name, which may be a genus or
family ("Oceanic dolphins") — `taxon_rank` says which. The individual species
probabilities live in `identification_json` under `resolution.members`.

## Incident lifecycle

```
intake → identifying → assessing → awaiting_dispatch → dispatched
                                                           ↓
                              accepted → en_route → on_scene → resolved
```

Three terminal states leave the main path:

- `guidance_only` — the animal is healthy, the reporter was advised, nobody is
  sent. Reached when severity scores `guidance`.
- `cancelled` — a duplicate, a false report, or the animal left.
- `resolved` — a responder closed it with a log entry.

Closing requires a log (`POST /incidents/{id}/log` sets `resolved` and writes
the entry in one call). That is deliberate: it is what keeps the ground-truth
dataset complete enough to evaluate the agents.

## Conversation state

`ConversationState` ([`chatbot/session.py`](../backend/lifejacket/chatbot/session.py))
is serialised into `incidents.conversation_state_json`.

It exists because each reporter reply is a separate HTTP request, possibly
minutes apart, possibly after the phone slept. The state holds the stage, the
transcript, the question counts, `probed_features` (so the agent does not
re-ask a question it already spent budget on), and two `*_stale` flags.

The stale flags matter: when the reporter answers, the agent that asked must
run again before anything else is decided. They are saved with the state
because the answer and the re-run happen in different requests. Dropping them
from serialisation would mean answers are stored but never acted on —
`backend/tests/test_api.py` drives a conversation over HTTP to guard this.

It is deliberately plain data: no clients, no sessions, no sockets. Serialise,
store, resume.

## Duplicates are linked, not deleted

A stranded animal on a public beach gets reported by everyone who walks past.
When `duplicates.find_duplicate` scores a match above the threshold,
`incidents.duplicate_of` points at the earlier incident and the new one is
cancelled.

The row is kept because two independent reports corroborate that something is
really there, and the second reporter may have sent a better photo.

Cancelling a report is the one place the system withholds a response, so two
rules limit when it may:

- **Only an incident someone is actively handling can be a duplicate target**:
  `awaiting_dispatch` through `on_scene`
  (`duplicates.ACTIVE_DUPLICATE_TARGET_STATUSES`). A case that ended is a new
  event if the animal is reported again. An intake nobody finished was never
  sent to anyone. A row that is itself a cancelled duplicate is excluded too,
  so duplicates do not chain into speculative clusters.
- **Reports that disagree on the animal group are never cancelled.** Distance
  and time alone can clear the threshold (a dolphin 200 m from a seal an hour
  later scores 0.765 against 0.70). Such a report is dispatched normally and
  the incident detail carries `possible_duplicate`, which the console shows as
  "Possible duplicate of ...", so a person decides. An *unknown* group is not a
  disagreement.

## Mass strandings are worked out, not stored

NOAA's definition: two or more cetaceans, same or mixed species, stranded at
the same time and place, other than a cow-calf pair. It needs a larger
response than one animal, and no single report shows it.

Two facts feed it. `assessment_json["animal_count"]` is how many animals one
report says are in trouble (1 unless the photos or the reporter indicate
more). And two incidents that were *not* linked as duplicates are, by the
system's own judgement, different animals.

`mass_stranding.find_mass_strandings` puts them together over the incidents
open right now:

- An incident and its linked duplicates are one scene. Its count is the
  **largest** any of those reports gave, never the sum, because the same
  animals are in several people's photos.
- Separate incidents within 2 km and 24 hours are one event, chained along the
  coast, and their counts are **added**.
- Two or more is a mass stranding. Cetaceans only: several seals on a beach is
  a haul-out.

There is no event table and no column for it. A report arriving now changes
the answer for an incident filed an hour ago, so `GET /incidents/{id}`
(`mass_stranding`, `animal_count`) and `GET /incidents` (`in_mass_stranding`)
compute it per request. Resolving an incident removes it from the event.

It does not change severity (a stranded cetacean is already critical) or who
is offered the dispatch. It tells the coordinator the scale.

Weaker matches stay in `metrics_json["duplicate_match"]` and are not shown.

## Ground truth

`incident_logs.confirmed_species` is the only place the system learns whether
it was right. It comes from
[`LogIncidentScreen.tsx`](../clients/responder_console/src/screens/LogIncidentScreen.tsx),
which is why that form is kept to four fields — a responder who has just spent
two hours on a beach will fill in four, not twelve.

Paired against predictions in
[`notebooks/02_agent_evaluation.ipynb`](../notebooks/02_agent_evaluation.ipynb).

## Relationship to the prototype's CSV

The previous pipeline used an append-only 45-column CSV, documented in
[`data/schema/incident_schema_v1.json`](../data/schema/incident_schema_v1.json).
Its own `storage_notes` record the problems: no locking, no updates or deletes,
and total loss on every Cloud Run deploy.

The schema file is kept for reference because the research data in
`data/seeds/example_incidents.csv` uses those column names. It is **not** the
current contract — `schemas.py` is.

## Migrations

There are none. `init_db()` calls `create_all`, which creates missing tables
and **silently ignores changed columns on existing ones**. During active schema
churn that is the right trade; once there is data worth preserving, add Alembic.

Until then: if you change a column, delete your local `lifejacket.db` (`make
clean`) and re-seed.
