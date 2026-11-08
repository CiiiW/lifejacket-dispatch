# Drone workflow readiness review

Reviewed November 7, 2026 (Chicago). Scope: case-linked observation prototype, with the Mini 2 held by a teammate.

The core coordinator workflow can be rehearsed without an aircraft. This does not establish field readiness, wildlife recognition accuracy, autonomous flight, or the usefulness of aerial footage.

| Area | Current coverage | Remaining acceptance |
| --- | --- | --- |
| Low-confidence / extra-photo suggestions | Provisional confidence threshold and explicit photo-evidence gap suggest a request for human review; urgent response stays parallel. | Independently labeled data are needed to calibrate the threshold and quantify false suggestions / missed evidence gaps. |
| Monitoring request | Coordinator can request observation, define an objective and escalation criteria, schedule review, and continue / escalate / finish monitoring. | Operational protocol and expert review for a suspected orphaned pup; being alone is not encoded as a confirmed orphan diagnosis. |
| Approval and operator handoff | Lead coordinator approves, names an operator and records feasibility confirmation. A private publishing grant does not grant case access. | Actual operator availability and field checks remain manual. No operator account/availability registry or aircraft telemetry integration. |
| Stream ingestion | Real RTMP receiver and bounded JPEG extraction; case-linked, expiring, publishing-only grant. | Exact Mini 2/controller/iPhone/DJI Fly combination, phone uplink and query-string handling need the ground test. |
| Coordinator preview | Sampled preview up to 2 fps; waiting / connected / interrupted / expired / ended; frozen images hidden. | Full-motion playback and audio are not implemented. Camera-to-screen delay and useful visual detail need measurement. |
| Evidence and provenance | Exact displayed frame ID, immutable saved image/hash, source/rights, reception timestamp; original intake preserved. | Camera capture time, video offset, animal position and aircraft telemetry are not inferred. |
| Reassessment | Coordinator compares observations and records answered / still uncertain / escalation needed. | Saved stream frames are not automatically sent to the AI identification/condition pipeline. Model-assisted reassessment is a separate software increment. |
| Revocation and failure | Failed/cancelled requests, case closure/transfer, invalid verification/submission/state, expiry and ended sessions block collection/publishing; stale writes are rejected. | Battery, flight-controller link loss and pilot availability are not automatically monitored. A stream outage alone does not reveal the reason. |
| Monitoring attention | In-app attention and due/overdue follow-through exist. | No background email/SMS/push delivery when the coordinator closes the app. Do not rely on the open-page queue as a field alert service. |
| Deployment and operations | Receiver defaults to loopback, private/VPN publishing, bounded buffers, one process with up to four decoder slots. | No phone-to-GCP private route has been provisioned or tested. Production supervision/alerts, concurrent-load testing, backup and an agreed evidence-retention policy remain deployment work. |
| Sharing and release | Work is committed on the feature branch and a disposable private rehearsal is available. | Branch is not pushed/merged and production feature flags remain off. |

## Corrections from this review

- Revoking submission, verification or a valid case state now invalidates the media grant as well as the case API. A resolved/cancelled/duplicate incident cannot obtain a new grant.
- Malformed recording references produce a validation response rather than an unhandled server error. Invalid receiver configuration is rejected safely.
- A temporary preview API outage clears the current picture, shows a retry message, and restores the preview when requests succeed again.
- The transport regression now restarts the actual receiver on the same ports and lock, preserving saved evidence and reconnecting with the still-valid grant.

## What to do next

1. Software increments if needed for the intended demo: explicit selected-frame AI analysis with results saved as a reviewed addendum; background reminder delivery with an agreed recipient/channel. These are not part of the completed manual-review prototype.
2. Deployment preparation: choose the private/VPN route, persistent runtime, receiver monitoring and evidence-retention policy before a real remote session.
3. Teammate ground test: use [the hardware checklist](drone_live_workflow.md#teammate-hardware-handoff), with motors off, to verify pairing, RTMP publishing, image detail, measured latency, interruption/reconnection and expiry.
4. Usefulness evaluation: compare the original report with paired real aerial evidence, reviewed independently by qualified domain reviewers. Measure correct identification/observation, remaining uncertainty, decision changes and review time; retain failure examples. A generated video validates transport only.

For the prototype, no aircraft control is required: the pilot uses DJI Fly and the coordinator reviews evidence. Any autonomous-flight integration is a separate project decision and is not implied by streaming support.


## Verification results

The expanded run passed **79 backend tests** (including the real MediaMTX/FFmpeg transport and receiver restart), **14 client API tests**, TypeScript validation and Ruff. The new revocation/malformed-reference checks reproduced seven failures before the fixes and passed afterward. The browser outage rehearsal displayed a retry warning with no frozen frame, then restored a connected preview automatically after three injected HTTP 503 failures. These results validate software behavior using disposable cases and generated video, not hardware or wildlife-model accuracy.
