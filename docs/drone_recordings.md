# Received-video recording and coordinator playback

## Connection

DJI Fly on the operator's iPhone publishes RTMP to the private MediaMTX receiver.
The coordinator creates the expiring, publishing-only address in the case's observation
session, then shares it privately with the pilot. The phone must reach the receiver on a
private/VPN route. The default loopback URL is for local rehearsal only. DJI Fly's own
camera preview does not automatically connect to LifeJacket. The exact Mini 2/controller/
iPhone/DJI Fly setup and URL handling still require a stationary, motors-off hardware test.

## Storage and configuration

Set `DRONE_RECORDINGS_ENABLED=true` in BOTH the API and receiver environments. Keep the
existing stream settings and share the same persistent `DATABASE_URL` and
`DRONE_EVIDENCE_DIR` across API, receiver and analysis worker. The flag defaults off.
The connected synthetic rehearsal enables it only in its disposable environment.

Files live under `DRONE_EVIDENCE_DIR/stream-recordings/<recording-id>/`. SQLite stores
recording status, server start time, segment offsets/durations, sizes and SHA-256 hashes
in the additive `case_drone_recordings` table. Run the existing database initialization
before deploying the new API (`init_db` also runs when the receiver starts). Existing
stream rows need no column changes. This is a private server-filesystem implementation;
no cloud bucket or public file URLs are created. Back up the database and evidence
volume together. A persistent mounted volume is required in a container/cloud runtime.

A second local FFmpeg reader copies the received video into roughly 10-second MP4
segments, split at source keyframes. Audio is excluded. No model receives the video.
Only finalized, probed segments are exposed, so the currently open segment is not yet
playable. H.264 video is the intended browser format; unsupported source codecs display
a playback error. This preserves received compressed video, not the higher-quality
camera original. Keep aircraft recordings separately.

Each connection gets a new recording; interruptions produce separate entries, not a
false continuous recording. Graceful stop finalizes its last segment. On receiver restart,
closed segments in the previous manifest are recovered; incomplete/unplayable files are
removed. A stale recorder heartbeat appears interrupted. A 30-minute recorder duration,
512 MiB per-stream storage ceiling (including reconnects), 64 MiB playable-segment ceiling
and 128 MiB free-space floor bound this prototype. Limits are checked on the receiver's
poll, so a high-bitrate stream can briefly exceed the storage ceiling before stopping.
A recording failure/limit does not imply that live preview stopped. Configure operational
retention, disk monitoring and backups before real use; no automatic deletion of retained
recordings is performed. A long missing-keyframe segment may not be playable if oversized.

## Coordinator interface

In Case → Drone observation:

- Live sampled preview and exact-frame saving remain unchanged.
- **Received recordings** shows recording/interrupted/complete/limited/failed states and
  the number of playable segments. Source connection and recording status are separate.
- **Play 0–10s** loads a private segment through the authenticated case API into a browser
  video player. Tokens are never put in video URLs. Object URLs are revoked on session
  changes, unmount and authorization errors; there is no persistent browser media cache.
- **Saved evidence moments** links saved frames to nearby video using SERVER reception
  time. Those links are explicitly approximate because camera timestamps, decoder timing
  and video PTS are not synchronized. The saved original frame is the exact evidence.
- **Connect DJI Fly** describes the operator handoff and private-network requirement.

Archived recordings remain available after ending the stream to users who still have case
access. Every listing and file read checks current case/request/stream scope. Missing or
modified files fail closed, and responses use private/no-store caching.

## Rehearsal and acceptance

Use the commands in [drone_live_workflow.md](drone_live_workflow.md#connected-browser-rehearsal).
Publish generated footage, wait for a segment to close, save a frame, open playback,
interrupt/reconnect, end the session and reopen the recording. No real account, animal,
flight, live Gemini call or external notification is involved in that rehearsal.

The transport regression in `backend/tests/test_drone_stream_receiver.py` uses real
MediaMTX/FFmpeg, checks recorded-file hashes and authenticated playback, reconnects and
restarts the receiver. Recording-specific tests cover unrelated case access, ended-session
playback, unknown segments, tampering and stale heartbeat behavior.

## AI and patrol scope

This change prepares the receiving, recording and evidence interface for an EXISTING case.
Saved-frame detection/assessment uses the existing explicit review workflow. YOLO weights,
automatic frame shortlisting and automatic patrol-to-alert integration are not supplied
by this recording change. The legacy drone-intake UI is not used to bypass the authenticated
case boundary. New patrol sightings need their own permissioned intake/duplicate-review
workflow before being connected to case creation.


## Local verification

The recording change passed 46 focused backend checks, including the real generated-video
RTMP recording/playback/reconnect/restart regression, and 16 client API checks. TypeScript,
UI bundling and Ruff passed. A connected rehearsal served the UI and a 715,218-byte MP4
segment over the case-authenticated API while the preview reported connected. This is
software/transport evidence, not a visual browser acceptance test, hardware acceptance or
wildlife AI validation. The code is prepared locally; it is not a deployed cloud receiver.


## Unified observation workspace

The request now opens a responsive workspace before the request-update form. Footage
(live preview plus received recordings) occupies the left column; saved original photos
and advisory findings share the right column. It stacks below 850 px. Selecting a photo
also selects that evidence in the AI controls, but never starts a model call. Selecting
another frame clears the animal/detection choices and requires a fresh confirmation.
Unknown animal location, capture-time limits, recording/demo provenance and human-review
status are kept visible. Existing comparison, approval and human-outcome forms remain.

Run `npm run test:observation-workspace` after installing root and console dependencies.
These React DOM checks cover photo/AI selection, authenticated playback handoff, stale
photo response cancellation, media cleanup on case changes and denied photo access.
TypeScript and the rehearsal bundle are separate checks. The connected user browser could
not reach this workspace's localhost rehearsal (connection refused), so visual browser,
mobile layout, actual video decoding and keyboard acceptance still need to be run from
an environment where the rehearsal URL is reachable. No visual acceptance is claimed.
