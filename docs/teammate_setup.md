# Run LifeJacket from VS Code

Use branch `charlotte-mini2-demo`. Open the repository folder in VS Code and use
its integrated terminal. These commands do not depend on Jupyter, a Workbench
URL, the author's home directory, or credentials copied from another developer.

## Reporter and dashboard demo — no GCP permission

Install Node.js 24.3 or newer and Git. The first install needs internet access.
From the repository root:

```bash
git fetch origin
git switch charlotte-mini2-demo
git pull --ff-only
npm ci
npm run setup:demos
npm run demo:network
```

Open <http://127.0.0.1:8082>. The same commands work from macOS, Windows or Linux
terminals; the launcher uses Node paths/process APIs rather than shell scripts.
Use `npm run demo:network -- --port 8083` if the default port is occupied.
Stop the launcher with Ctrl+C.

- **Rescue dashboard:** select Fictional California Center, select its case,
  reveal the allowed text contact, and confirm response updates. Try NOAA to
  inspect read-only access. Do not actually call/text the fictional contact.
- **Reporter:** select “Start with completed fictional draft,” prepare a report,
  enter an invented phone number, check the verification notice and enter fixture
  code `123456`. Submit, check status and try leaving/contact withdrawal.

These are two independent, explicitly labeled UI fixtures. They do not share
case state, store data, perform real AI identification, send SMS or contact a
rescue center. Reloading resets fixture state. The static server binds only to
127.0.0.1, serves only generated demo assets, and blocks browser API connections
with a content security policy. It does not read `.env` or enable an auth bypass.
No Python, Docker, GCP login, private NOAA workbook, drone or Pi is needed here.

After a later pull, rerun `npm ci` and `npm run setup:demos` if lockfiles changed,
then restart `npm run demo:network`. Build and check the local launcher with:

```bash
npm run check:demos
npm run test:local-demo
```

## Local backend development and tests

Install Python 3.11 or newer. From the root:

```bash
python -m venv .venv
```

Select `.venv` with **Python: Select Interpreter** in VS Code. Activate it using
`.venv\Scripts\Activate.ps1` on Windows or `source .venv/bin/activate` on macOS/Linux.
Then install and test:

```bash
python -m pip install -r backend/requirements.txt pytest ruff
python -m pytest backend/tests/test_network_actions.py backend/tests/test_reporter_phone.py backend/tests/test_access_sessions.py backend/tests/test_network_routes.py backend/tests/test_network_policy.py
```

Those tests create isolated temporary SQLite databases and inject fictional
verified identities. They need no GCP IAM access and do not relax the production
managed-token verifier. The Python requirement ranges are not a fully pinned
cross-platform environment; report dependency installation failures rather than
reusing someone else's private environment or credentials.

To start the actual API for development:

```bash
python -m uvicorn lifejacket.api.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

The API can start with local SQLite and defaults, but starting it is not proof
that model calls or live authentication are configured. The older Docker-based
synthetic drone demo is documented separately in `local_drone_demo.md`.

## Actual live clients — configuration is still required

| Feature | Needed on the teammate's machine |
| --- | --- |
| Live AI intake | Their own Google Application Default Credentials and access to the configured Vertex AI project/model |
| Real dashboard authentication | Public Firebase/Auth client config, configured sign-in provider and matching backend auth project |
| Server-side revocation/disabled-user checks | The local backend's ADC identity must have `firebaseauth.users.get` in the auth project |
| Real SMS verification | Approved app domain, enabled phone provider, SMS billing/region/abuse controls and a real user verification test |
| Staff operations | Explicit approved memberships/case scopes and `NETWORK_CASE_ACTIONS_ENABLED=true` after setup |

The Workbench service account's current IAM block is specific to that runtime.
A teammate's local backend uses **their own ADC identity**; they do not need
permission to administer IAM or use the Workbench VM merely to develop locally.
Their identity still needs the relevant API permissions for real cloud services.
Never copy the Workbench `.env`, service-account keys, OAuth secrets or tokens into Git.

Use the committed `.env.example` files as templates; set only values appropriate
to the local environment. Normal live web commands are `npm run web` in the
respective client directory. For the dashboard, set `EXPO_PUBLIC_NETWORK_MODE=true`.
The live backend must enable network auth plus the appropriate reporter/actions
flags and use the matching auth project. A local direct API at localhost avoids
the Workbench proxy header behavior, but it still needs actual identity verification.

The reporter's current verified flow is browser-based, including on iPhone.
Native SMS support requires a development build; the default native wrapper does
not fall back to unverified intake. See `reporter_phone.md`, `network_console.md`
and `rescuer_response_flow.md` for exact live setup and permission boundaries.

Validation: a clean Linux source copy with no existing `.env` or node_modules passed `npm ci`, `npm run setup:demos`, `npm run check:demos` and `npm run test:local-demo`. Both pages were opened in the browser and the fictional reporter submission completed without backend/cloud access. macOS/Windows native installs were not executed in this session.

## Connected backend scenario (optional Python check)

The Node-only demos above are independent UI fixtures. To exercise one case through
real API routes and database policies across a reporter, two centers and NOAA, run
`python scripts/run_connected_scenario.py` in the backend Python environment, then
open `var/connected-workflow/latest.html` or restart the Node launcher and choose
**Connected rescue scenario**. This uses a disposable database and fictional identity/
intake adapters, without GCP or a public server. See `connected_scenario.md` for limits.
