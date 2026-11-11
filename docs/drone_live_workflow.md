# Case-linked live observation workflow

Status: software rehearsal; DJI Mini 2 / iPhone hardware acceptance remains pending.

## Coordinator workflow

1. Review a verification suggestion or create a monitoring request. Approve it and assign the responsible operator.
2. Confirm feasibility and move the request to in progress. Streaming cannot start before that confirmation for an operator flight.
3. Open a private observation session in the request. Enter a descriptive label and rights/credits. A recorded-demo request also needs an HTTPS source reference.
4. Copy the publishing address privately to the operator. It is shown only when created, expires after 30 minutes, grants publishing only, and cannot read case data. If lost, end the session and create a replacement.
5. Watch the sampled preview (up to 2 frames/second). This version is not a full-motion player and has no audio. A feed older than 6 seconds is hidden and marked interrupted.
6. Describe the observation and save the displayed frame. Only explicitly selected frames become immutable evidence. Frame selection uses an exact frame ID, retained in a bounded 12-second buffer, so a newer incoming frame cannot silently replace the selection.
7. End the session. Use the existing evidence-ready and reviewed steps, comparison and monitoring follow-up. Answered / still uncertain / escalation needed are human decisions. No assessment or rescue status is automatically replaced.

Server reception time is recorded separately from capture time. Camera capture time, source video offset, animal GPS and aircraft GPS remain unknown unless independently supplied through another verified workflow. A stream does not establish that an animal is healthy, absent or orphaned.

## Receiver preparation

Install MediaMTX **v1.21.3** from its official release and verify the release checksum. Install FFmpeg/FFprobe. The receiver is one process per database and supports up to four simultaneous decoders; use a dedicated instance for this prototype.

Use the same DATABASE_URL, evidence directory and settings in the API and receiver. Configure:

- NETWORK_AUTH_ENABLED=true
- CASE_DRONE_REQUESTS_ENABLED=true
- DRONE_STREAMS_ENABLED=true
- DRONE_STREAM_RECEIVER_SECRET: a random URL-safe secret of at least 32 characters, held in the environment/secret manager, never committed.
- DRONE_STREAM_PUBLISH_BASE: rtmp://127.0.0.1:19350/live for local rehearsal; later a private/VPN interface address reachable by the phone.

Run from repository root, with backend on PYTHONPATH:

~~~sh
python scripts/drone_stream_receiver.py --mediamtx /absolute/path/mediamtx --ffmpeg /absolute/path/ffmpeg
~~~

The receiver binds RTMP 19350, RTSP 18554, its control API 19997 and auth callback 18941 to loopback by default. Only RTMP can be bound to a selected private/VPN interface with --bind. RTSP, control and auth stay on loopback. The normal authenticated LifeJacket API serves previews; the browser never receives receiver credentials. Disable other MediaMTX protocol servers and recording. Publish credentials cannot read streams. The receiver checks case/request activity and disconnects ended/expired/invalid publishers through the control API, normally within the one-second poll plus API timeout. Killing the receiver shuts down its media server and collectors.

Do not expose raw RTMP on the public Internet: this implementation requires a private/VPN route for phone use. RTMPS support in the phone is not assumed, and this receiver launcher does not provision TLS. Jupyter's HTTP proxy cannot carry RTMP; a working web preview URL does not make the phone ingest address reachable. Deployment/network setup remains a separate acceptance item.

Transient frame storage is bounded to 20 JPEGs of at most 256 KiB each per session, decoded to 640-pixel width. The running receiver clears ended/expired/inactive buffers. Stopping the receiver can leave its last bounded buffer in the private database until cleanup/restart; no full-video archive is created. Selected evidence follows the existing evidence retention policy. Use a dedicated database for synthetic rehearsals.

## Recorded rehearsal

Use a recorded-demo request and a recording with verified reuse rights. NOAA hosting alone does not prove that third-party footage is reusable; record the specific source and credit. A generated test-pattern video is sufficient to test transport and permissions, but cannot validate animal detection or observation usefulness.

Save the newly created grant response privately as JSON, with its source metadata and publish_url, outside the repository (file mode 600). The helper refuses operator-flight grants:

~~~sh
python scripts/drone_stream_replay.py --video /private/clip.mp4 --grant-file /private/grant.json --ffmpeg /absolute/path/ffmpeg --ffprobe /absolute/path/ffprobe
~~~

Verify waiting -> connected, save a frame, stop publishing, verify interrupted and no frozen image, reconnect within the session lifetime, then end and verify disconnection/rejected reconnect. Finish evidence review and set a next review time if still uncertain. Do not paste publishing addresses into issues, screenshots or logs.

Run repeatable transport verification with a disposable synthetic case and generated MP4:

~~~sh
MEDIAMTX_BINARY=/absolute/path/mediamtx FFMPEG_BINARY=/absolute/path/ffmpeg python -m pytest backend/tests/test_drone_stream_receiver.py -q
~~~

## Teammate hardware handoff

Record device model and iOS version, DJI Fly version, original Mini 2 model, controller model (expected RC-N1), aircraft/controller firmware and phone cable. No flight is needed for the initial connection test.

- Confirm the camera image in DJI Fly with the aircraft stationary and motors off.
- Locate GO FLY -> Transmission -> Live Streaming Platforms -> RTMP. Confirm it is available on that exact app/controller combination.
- Confirm the phone can reach the private receiver while still connected to the controller, and has sufficient Internet/VPN connectivity.
- Use a new operator-flight request and grant. Start a short ground stream, check remote preview, save a frame, and compare a visible clock to measure delay. Server receipt age is not end-to-end camera latency.
- Interrupt the uplink: the coordinator must see interrupted rather than an apparently current frozen image. Reconnect, end, and confirm the old publishing address is rejected.
- After this passes, separately evaluate actual aerial footage, battery/radio behavior, target visibility and the usefulness of the evidence with the appropriate operator. None of these are established by the software rehearsal.

Operator naming does not grant an app account or flight permission. The coordinator hands over the short-lived publishing address; the operator uses DJI Fly and operates the aircraft manually. No DJI SDK integration, autonomous dispatch, waypoint flight or automatic animal tracking is implemented.

## Primary references

- DJI Fly livestream operation: https://repair.dji.com/help/content?customId=en-us03400006727&lang=en&paperDocType=paper&re=US&spaceId=34
- MediaMTX HTTP authentication and RTMP credentials: https://mediamtx.org/docs/features/authentication
- MediaMTX configuration: https://mediamtx.org/docs/references/configuration-file
- MediaMTX releases: https://github.com/bluenviron/mediamtx/releases


## Connected browser rehearsal

With development dependencies installed, build the actual request UI:

~~~sh
npm ci
npm ci --prefix clients/responder_console
npm run build:drone-stream
python scripts/check_drone_setup.py --mediamtx /absolute/path/mediamtx --ffmpeg /absolute/path/ffmpeg
python scripts/drone_stream_demo.py --mediamtx /absolute/path/mediamtx --ffmpeg /absolute/path/ffmpeg --port 8935
~~~

Open the authenticated Workbench proxy for port 8935. The server is loopback-only and uses a disposable database, synthetic identity, a generated MP4 and a real RTMP receiver. It seeds an approved, in-progress recorded-demo request so you can save frames and complete review. It never connects to production data or a drone. Stop this rehearsal before running receiver integration tests because it uses the same private media ports. Restart it to reset the synthetic case. The initial stream expires after 30 minutes; shutdown removes disposable data and stops its media children.


## Verification on 2026-11-07

- 55 backend checks passed, including the opt-in real MediaMTX/FFmpeg RTMP rehearsal with a generated MP4.
- 14 client API checks, TypeScript validation and Ruff passed.
- Browser rehearsal saved an exact displayed frame, ended the stream, submitted evidence for review, recorded still uncertain, and scheduled follow-up. Stream reception time remained separate from unknown camera capture time; the original case assessment was preserved.
- Bad publishing credentials, non-lead writes, unrelated case access, stale frames, expiry and loss of case participation are covered. The transport check verified interruption, reconnect and publisher disconnection on end. The receiver exits with its media children on termination.
- Physical Mini 2/iPhone pairing, DJI Fly URL handling, private-network reachability, camera-to-screen delay and usefulness of aerial wildlife footage remain hardware acceptance items.


See [drone_workflow_readiness.md](drone_workflow_readiness.md) for the latest coverage review and remaining software, deployment and hardware acceptance items.


Saved-frame AI jobs and closed-app reminder delivery are described in [drone_followup.md](drone_followup.md).


## Setup boundaries before the hardware test

The rehearsal uses the actual coordinator request/stream/evidence UI and case APIs.
It is intentionally disposable: stopping it removes its generated media and test database.
Do not use it for real animal evidence. A deployed API, receiver and analysis worker must
share persistent database/evidence storage and the same configuration.

The live receiver is a sampled-preview and selected-still workflow. It does not retain a
full-video archive or offer full-motion playback. Recorded-file selection separately copies
the original local clip into its output directory; that is not a live archive or a console
video player. Keep original aircraft recordings separately until an archive workflow exists.

Before involving YOLO, verify stream reception, exact-frame saving, original-photo access,
interruption/reconnection, end-session revocation and the human review flow. AI outputs in
the rehearsal are fixtures. YOLO integration and patrol-to-alert creation are separate work;
this setup exercises an observation request linked to an existing case.

For a remote phone, select a private/VPN route to the receiver with the project operator.
The default loopback URL cannot be reached by an iPhone. An HTTP app/proxy URL does not
carry RTMP. No public receiver, VPN, external notification destination or cloud service is
provisioned by these commands.
