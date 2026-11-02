# One isolated connected rescue scenario

This verifies one case through the real backend routes and database permission
checks, without live users, SMS, model calls or a public API server.

## Run in VS Code

Use Python 3.11+ with the backend requirements installed, as described in
`teammate_setup.md`. From the repository root with that environment active:

```bash
python scripts/run_connected_scenario.py
```

The equivalent npm shortcut is `npm run demo:connected` (it still requires the
Python backend environment). Successful runs generate:

- `var/connected-workflow/latest.json`: redacted, machine-readable API-check results.
- `var/connected-workflow/latest.html`: readable report and reporter timeline.

Open the HTML directly, or start/restart `npm run demo:network` and follow
**Connected rescue scenario** at <http://127.0.0.1:8082/connected/>. The Node server
serves the last completed report, not an interactive API or live case feed.
The two original reporter/dashboard UI fixtures remain independent.

## What is connected

1. Real `/access/me` logic creates personal identities without auto-granting roles.
2. Trusted scenario setup approves two fictional California centers and NOAA memberships.
3. The reporter starts a real private draft. Premature submission is denied; the
   synthetic prepared intake is then explicitly submitted by a fictional phone identity.
4. The trusted offline review service (also used by the admin CLI) reviews state and
   designates Center A as lead while preserving the submitted reporter ownership.
5. Both centers and NOAA discover that same submitted case. Statewide discovery
   alone grants neither reporter contact nor update permission.
6. Trusted setup accepts Center B as support and assigns its rescuer. That rescuer
   gains permitted text-only contact, then loses it when the reporter withdraws consent.
7. The assigned support rescuer records accepted, en route, arrived and animal
   located as separate confirmed events. The reporter and NOAA read the same phases
   from the same database. Stale writes are denied.
8. Only Center A's lead coordinator closes the case. A revoked membership is denied;
   closed-case contact is unavailable. Audit records match the confirmed sequence.

All actor capabilities come from the normal database membership/case policies;
the test does not replace `current_access_session` with a hand-written Principal.
The only identity substitution is a strict fictional token allowlist in the child
process, at the managed-provider verification boundary. Unknown tokens are denied.

## Isolation and limits

The public command creates a new temporary directory and database and starts a
child process. The child disables dotenv loading for backend settings, forces its
new SQLite/photo paths before backend imports, blocks external socket connections,
and calls the app through in-process ASGI TestClient. It exposes no server and
cannot be selected as an authentication mode by the production app. The temporary
database is disposed and removed after the run; only redacted report artifacts remain.
An inherited `DATABASE_URL` is overridden, never opened. Tests supply a sentinel
file as that inherited database and verify it is untouched.

Phone verification and the completed intake are simulated: no real photo is
identified, no SMS is sent, and injury assessment is not evaluated. Center approval,
support acceptance and individual assignment are explicit trusted fixture setup,
not a claim that their production onboarding/invitation UIs exist. Case review
runs the actual offline administrative service; there is no public review UI.
ETA stays unavailable because a reviewed arrival source is not connected. No calls,
texts, push notifications or rescue dispatches are sent. JSON/HTML outputs omit
raw credentials, draft keys, reporter contact numbers and responder coordinates.

## Gaps surfaced by this scenario

- Resolved: the offline review command now completes the first review of a submitted
  phone report. It preserves verified ownership, requires an approved lead for the
  reviewed state, audits the review and rejects existing operational metadata or
  concurrent/repeated review. The scenario now exercises that service.
- Support requests/acceptance, organization onboarding and assignment approval need
  their own authorized production workflows. A fixture database edit is not that UI.
- Real SMS/email delivery, managed-token verification/IAM, connected browser clients,
  arrival estimates and notifications remain separate integration work.

Run the isolation/connected-flow regression with:

```bash
python -m pytest backend/tests/test_connected_scenario.py
npm run test:local-demo
```

Validation: the connected run passed 42 actual in-process API checks, including expected authorization denials and the full reporter timeline. The case-review, scenario/isolation, access, network, reporter and response regression selection passed 94 tests. The local launcher integration check passed with the connected-report route. No live identity provider, AI intake or production coordination setup is claimed.
