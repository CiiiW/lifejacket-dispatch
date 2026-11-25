# Drone workflow readiness review

Updated November 24, 2026 (Chicago). The case-linked prototype was exercised with the original DJI Mini 2, iPhone and private Mac receiver.

The core coordinator workflow can be rehearsed without an aircraft. This does not establish field readiness, wildlife recognition accuracy, autonomous flight, or the usefulness of aerial footage.

| Area | Current coverage | Remaining acceptance |
| --- | --- | --- |
| Low-confidence / extra-photo suggestions | Provisional confidence threshold and explicit photo-evidence gap suggest a request for human review; urgent response stays parallel. | Independently labeled data are needed to calibrate the threshold and quantify false suggestions / missed evidence gaps. |
| Monitoring request | Coordinator can request observation, define an objective and escalation criteria, schedule review, and continue / escalate / finish monitoring. | Operational protocol and expert review for a suspected orphaned pup; being alone is not encoded as a confirmed orphan diagnosis. |
| Approval and operator handoff | Lead coordinator approves, names an operator and records feasibility confirmation. A private publishing grant does not grant case access. | Actual operator availability and field checks remain manual. No operator account/availability registry or aircraft telemetry integration. |
| Stream ingestion | Real RTMP receiver and bounded JPEG extraction; case-linked, expiring, publishing-only grant. | DJI Fly and Litchi streamed video to LifeJacket during motors-off tests over private Wi-Fi. Streaming while flying a waypoint route remains untested. |
| Waypoint handoff | The fictional patrol CSV imported into Litchi Legacy Mission Hub and loaded on the iPhone. The separate ArduPilot simulator path verified upload and readback. | Outdoor waypoint execution with live video and pilot takeover. |
| Coordinator preview | Sampled preview up to 2 fps; waiting / connected / interrupted / expired / ended; frozen images hidden. | Full-motion playback and audio are not implemented. Camera-to-screen delay and useful visual detail need measurement. |
| Evidence and provenance | Exact displayed frame ID, immutable saved image/hash, source/rights, reception timestamp; original intake preserved. | Camera capture time, video offset, animal position and aircraft telemetry are not inferred. |
| Reassessment | Coordinator compares observations and records answered / still uncertain / escalation needed. | Selected saved frames now support queued detection and selected-animal AI assessment with human review. Enable the analysis worker and validate real imagery before field use. |
| Revocation and failure | Failed/cancelled requests, case closure/transfer, invalid verification/submission/state, expiry and ended sessions block collection/publishing; stale writes are rejected. | Battery, flight-controller link loss and pilot availability are not automatically monitored. A stream outage alone does not reveal the reason. |
| Monitoring attention | In-app attention and due/overdue follow-through exist. | A durable background reminder worker and signed, deduplicated lead-organization webhook transport now exist. A real destination/channel and supervised worker still require activation; email/SMS/push providers are not implicitly connected. |
| Deployment and operations | Receiver defaults to loopback, private/VPN publishing, bounded buffers, one process with up to four decoder slots. | No phone-to-GCP private route has been provisioned or tested. Production supervision/alerts, concurrent-load testing, backup and an agreed evidence-retention policy remain deployment work. |
| Sharing and release | The branch is on GitHub in [draft PR #25](https://github.com/CiiiW/lifejacket-dispatch/pull/25). A disposable private rehearsal is available. | Merge and production deployment remain separate. |

## Corrections from this review

- Revoking submission, verification or a valid case state now invalidates the media grant as well as the case API. A resolved/cancelled/duplicate incident cannot obtain a new grant.
- Malformed recording references produce a validation response rather than an unhandled server error. Invalid receiver configuration is rejected safely.
- A temporary preview API outage clears the current picture, shows a retry message, and restores the preview when requests succeed again.
- The transport regression now restarts the actual receiver on the same ports and lock, preserving saved evidence and reconnecting with the still-valid grant.

## What to do next

1. Activate follow-up workers after configuring the model runtime and the authorized lead-organization delivery destination. See [drone_followup.md](drone_followup.md). The private rehearsal uses fixture AI outputs and a local reminder sink; it makes no live model calls or external deliveries.
2. Deployment preparation: choose the private/VPN route, persistent runtime, receiver monitoring and evidence-retention policy before a real remote session.
3. Verify an outdoor Litchi waypoint route with a simultaneous LifeJacket preview. Measure camera-to-screen delay and record interruptions and pilot takeover. The [November 24 ground-test record](drone_live_workflow.md#ground-test-results-on-2026-11-24) documents the hardware checks already completed.
4. Usefulness evaluation: compare the original report with paired real aerial evidence, reviewed independently by qualified domain reviewers. Measure correct identification/observation, remaining uncertainty, decision changes and review time; retain failure examples. A generated video validates transport only.

The pilot uses DJI Fly for manual flight or Litchi for waypoint planning and launch. LifeJacket prepares the route, receives the stream and supports coordinator evidence review.


## November 7 software verification

The expanded run passed **79 backend tests** (including the real MediaMTX/FFmpeg transport and receiver restart), **14 client API tests**, TypeScript validation and Ruff. The new revocation/malformed-reference checks reproduced seven failures before the fixes and passed afterward. The browser outage rehearsal displayed a retry warning with no frozen frame, then restored a connected preview automatically after three injected HTTP 503 failures. These results validate software behavior using disposable cases and generated video, not hardware or wildlife-model accuracy.
