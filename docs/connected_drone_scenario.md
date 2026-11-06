# Connected drone request scenario

Run from the repository root in the backend Python environment:

```bash
python scripts/run_connected_scenario.py --with-drone
```

This extends the existing isolated reporter/two-center/NOAA scenario with the actual
case-linked drone request routes. It writes a redacted JSON trace and a readable
HTML report under `var/connected-drone-workflow/`.

## What runs

1. A fictional phone-verified reporter starts and submits a private draft.
2. Prepared low-confidence intake is installed by a clearly labeled fixture.
3. The trusted offline case-review service assigns Center A without changing reporter ownership.
4. The lead sees one automatic suggestion from actual persisted confidence values.
5. Coordinator creation, approval and evidence collection use real request endpoints.
6. A generated PNG passes through the real upload/download routes and is checked byte-for-byte.
7. Human review records still uncertain and a follow-up time on the same case.
8. Database queries verify one request, one frame and six versioned events.
9. The original intake and rescue response phase remain unchanged during drone review.
10. Later fictional field-response confirmations finish the original connected scenario separately.

The run checks anonymous/reporter/unrelated-center access, cross-case evidence access,
missing approval/operator/outcome, premature completion, stale revisions and duplicate retries.
Recorded-demo review must leave the operational suggestion available.

## Isolation

- Separate child process and new temporary database/evidence directories.
- Inherited database/evidence settings and repository .env are ignored.
- Synthetic provider-token verification is installed only in the child; membership resolution is real.
- External sockets are blocked. No HTTP API server, live SMS, model calls, notifications or physical flight.
- Temporary database and evidence are removed after success.
- Exported reports contain aliases and a generated frame, not draft credentials, tokens or phone numbers.

This tests backend integration and persistence. It does not establish live managed-auth deployment,
AI accuracy, aerial recognition, NOAA footage licensing, Mini 2 flight control or the production UI/API connection.

## View the completed report

```bash
python scripts/serve_network_ui_fixture.py --web-dir var/connected-drone-workflow --port 8932
```

Open the loopback URL (or authenticated Workbench proxy for port 8932).
This serves the completed static report, not an interactive or mock-auth backend.

## Regression

```bash
python -m pytest backend/tests/test_connected_drone_scenario.py backend/tests/test_connected_scenario.py
```

The new regression provides inherited database/evidence sentinels, validates cleanup,
and checks request/evidence linkage, audit sequence, source integrity, original-intake
preservation and report redaction. Existing default rescue-only behavior is retained.
