# Saved-frame AI reassessment and background reminders

## Coordinator workflow

Save a photo/frame as case evidence. In **Analyze saved evidence**, explicitly confirm sending that frame for advisory AI screening, then select **Detect animals**. The job is persisted and processed by the separate analysis worker. Select a completed detection and the intended animal, confirm again, and choose **Assess selected animal**.

The existing detection, identification and condition agents are reused. The frame hash is checked before analysis; the selected animal crop is used. Camera capture time stays unknown when only reception time is available. Operator notes, source URLs and the original report are not sent as model instructions. Viewpoint remains unverified. Weather/tide and movement over time are not inferred from one frame.

Results, model metadata, source evidence and job status are saved separately from intake. A coordinator uses the existing evidence review to record the finding and outcome. AI does not overwrite the original assessment, close the case, dispatch responders or establish that an animal is healthy/absent. Empty detection requires manual review. Aerial performance is still unvalidated.

Jobs have an idempotent creation key, an atomic worker lease, access checks before and after inference, safe error codes, and explicit retry after failure. Disabled accounts, revoked memberships, changed lead organizations, invalid case verification and completed/closed cases cancel pending work. An abandoned worker lease can be reclaimed; the old worker cannot overwrite a newer result. Model calls may still incur cost before an access change is detected, but their results are discarded.

## Background reminders

The reminder worker scans the durable case database even when no coordinator page is open. It derives overdue observation reviews and escalation attention from the existing workflow and creates one outbox item per current lead organization and attention key. Closing/transferring a case, revoking verification, changing the schedule or acknowledging attention cancels unsent items. Existing professional organization approval is checked before delivery.

Destinations are configured by the operator **per lead organization**, not supplied through a user request. The first transport is an HTTPS webhook suitable for an organization's notification automation/inbox. No actual destination is configured or activated by this implementation. Email, SMS and push fan-out can be handled by the configured receiver; those providers are not implicitly connected.

Each callback contains only schema/event identifiers, organization ID, case ID, request ID, kind, attention key and creation time. It excludes reporter contact, GPS, photos, free-text findings and the publishing address. It carries:

- Idempotency-Key: the stable notification ID.
- X-LifeJacket-Signature: sha256= plus HMAC-SHA256 of the exact request body, using that organization's signing key.

The receiver must validate the signature, deduplicate by notification ID, and route to an authorized coordinator inbox. Delivery is **at least once**, not exactly once: a timeout can occur after the receiver accepted a request. Retries keep the same ID and body. Redirects are rejected, HTTP calls time out, and retries back off with a five-attempt limit. Failed items stay visible and the lead coordinator can explicitly retry them. Delivered means the destination accepted the callback, not that a human read it. Delivery never acknowledges attention or changes rescue status.

Missing destination/signing-key configuration is visible as blocked. A missing/stale worker heartbeat is shown in the UI; queued work is not represented as delivered. The app can show status while open, but the separate worker must be supervised for closed-app delivery.

## Configuration and deployment

All feature flags default off. Use the same persistent database, evidence directory and configuration in the API and workers:

~~~text
NETWORK_AUTH_ENABLED=true
CASE_DRONE_REQUESTS_ENABLED=true
DRONE_FRAME_ANALYSIS_ENABLED=true
DRONE_REMINDERS_ENABLED=true
DRONE_REMINDER_WEBHOOKS={"CENTER_ID":"https://your-authorized-receiver.example/your-private-endpoint"}
DRONE_REMINDER_SIGNING_KEYS={"CENTER_ID":"a-random-secret-of-at-least-32-characters"}
~~~

Keep real destinations/keys in a protected environment file or secret manager, never in git. The analysis worker uses the existing model configuration and GCP application credentials. Start workers separately so a slow model call cannot delay reminders:

~~~sh
python scripts/drone_followup_worker.py --kind analysis
python scripts/drone_followup_worker.py --kind reminders
~~~

The --once option performs one cycle for a scheduler or smoke test. The long-running worker checks queued work continuously and persists heartbeats. The systemd template in deploy/lifejacket-drone-followup@.service is a deployment starting point; adjust user, paths, credentials and the protected environment file before installation. Use two instances (analysis and reminders). No service is installed or enabled automatically.

Before activation, configure the actual organization route and authorized recipient channel, run an end-to-end delivery test to that destination, and verify restart, retry, cancellation and monitoring behavior. This requires a destination supplied by the project owner. A configured webhook and a running worker do not prove an email/SMS/push reached a human.

## Private rehearsal and validation limits

The connected stream rehearsal uses the real case routes and durable workers with a generated MP4, **fixture AI outputs**, and a **local reminder sink**. No external messages or live model calls are made by this rehearsal. It demonstrates save frame -> detect -> choose animal -> assess -> coordinator review and a reminder recorded independently of the page. The real model adapter is exercised with deterministic test clients; these tests establish integration and provenance, not wildlife-model accuracy.

Physical DJI/iPhone connectivity, private-network deployment, real aerial evidence, expert review, confidence calibration and the receiver's actual downstream notification channel remain acceptance work. The existing Mini 2 checklist still applies.


## Browser acceptance

The connected private rehearsal completed save-frame, detection, explicit animal selection, advisory assessment, end-session, evidence-ready, coordinator review (still uncertain), and next-review scheduling. A reminder was captured by the local sink independently of the page. Both AI stages in this rehearsal used labeled fixture outputs, not a live wildlife model. No external notification destination was contacted.


## Verification

98 backend regression checks and 15 client API checks passed, together with TypeScript and Ruff. Coverage includes saved-frame integrity and crop selection, real authorization rechecks before/after inference, idempotent enqueue, atomic leases and abandoned-worker recovery, standalone worker commands, reminder signatures and stable retry IDs, failure limits, missing-destination recovery, and cancellation after acknowledgment/closure/transfer/revocation. Model and delivery calls were replaced with deterministic fixtures in these tests. Live Vertex inference quality and actual downstream message receipt are separate acceptance checks.
