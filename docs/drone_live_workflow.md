# Case-linked live observation workflow

Status: motors-off waypoint handoff and live video verified on the DJI Mini 2 and iPhone. Outdoor waypoint flight with live video remains untested.

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

The receiver binds RTMP 19350, RTSP 18554, its control API 19997 and auth callback 18941 to loopback by default. Only RTMP can be bound to a selected private/VPN interface with --bind. RTSP, control and auth stay on loopback. The normal authenticated LifeJacket API serves previews; the browser never receives receiver credentials. Disable other MediaMTX protocol servers and native MediaMTX recording. Optional LifeJacket received-video segments are described in [drone_recordings.md](drone_recordings.md). Publish credentials cannot read streams. The receiver checks case/request activity and disconnects ended/expired/invalid publishers through the control API, normally within the one-second poll plus API timeout. Killing the receiver shuts down its media server and collectors.

Do not expose raw RTMP on the public Internet: this implementation requires a private/VPN route for phone use. RTMPS support in the phone is not assumed, and this receiver launcher does not provision TLS. Jupyter's HTTP proxy cannot carry RTMP; a working web preview URL does not make the phone ingest address reachable. Deployment/network setup remains a separate acceptance item.

Transient frame storage is bounded to 20 JPEGs of at most 256 KiB each per session, decoded to 640-pixel width. The running receiver clears ended/expired/inactive buffers. Stopping the receiver can leave its last bounded buffer in the private database until cleanup/restart; no full-video archive is created unless DRONE_RECORDINGS_ENABLED is explicitly enabled. Selected evidence follows the existing evidence retention policy. Use a dedicated database for synthetic rehearsals.

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

The coordinator gives the operator a short-lived publishing address. The pilot uses DJI Fly or Litchi for the camera feed and uses Litchi to review the waypoint route. LifeJacket generates the plan and receives evidence for coordinator review.

### Start an isolated phone rehearsal

Use a CPU host on the phone's trusted LAN, or a host with a private IPv4 route
the phone already has access to. On that host, build the rehearsal UI and launch
the receiver with its specific private interface address:

~~~sh
npm run build:drone-stream
python scripts/drone_stream_demo.py --mediamtx /absolute/path/mediamtx \
  --ffmpeg /absolute/path/ffmpeg --phone-bind <host-private-ipv4>
~~~

The coordinator UI stays on loopback port 8935. Open it on the host or through
an existing authenticated HTTP proxy. The phone needs a separate route to the
private RTMP listener on TCP 19350. The browser proxy does not provide that path.
Only use this mode on a trusted LAN or an existing private route. The launcher
does not configure a firewall or make the receiver public.

The rehearsal opens a disposable test case with a requested operator observation.
Approve it in the coordinator UI, record the ground-test readiness check,
and create a private session. Give the phone the session URL privately. The
preview starts in **Waiting** until the phone publishes. Save and reopen a
frame, interrupt the phone connection, reconnect, and end the session. The
launcher does not record the full stream in this mode. Stopping it discards
the test case and its saved frames.

## Litchi ground rehearsal

1. On a fictional case with a saved search area, choose **Preview patrol → Mission
   handoff → Download draft waypoints (CSV)**. The export contains survey coordinates
   only. Launch, return, landing and altitude settings require pilot review.
2. Open [Litchi Legacy Mission Hub](https://flylitchi.com/hub), choose **Missions →
   Import**, check the points on the map and save the mission privately. On iPhone,
   use the same Litchi account and load the mission in **Waypoint → Load**.
3. Keep the Mini 2 stationary with its motors off. Fully close DJI Fly before
   opening **Litchi for DJI Drones**. Confirm that the camera image is visible in
   **FPV** before starting the stream.
4. Open a private LifeJacket observation session. On the same private network,
   paste the full publishing address into **FPV → Share Video Stream → RTMP
   Streaming**. Verify **Connected** and an advancing reception timestamp
   in LifeJacket. Tap **End Live** in Litchi when done.

In this rehearsal, Litchi did not initially appear in iOS Local Network settings.
Selecting **Share Video Stream → Litchi Vue** triggered the permission prompt.
An initial RTMP attempt showed **End Live** in Litchi while LifeJacket received
no frames and the camera view in Litchi was blank. DJI Fly then published to the
same address as a receiver check. After the Litchi camera connection was
restored, retrying RTMP produced fresh frames in LifeJacket.

## Ground-test results on 2026-11-24

| Check | Observed result |
| --- | --- |
| Waypoint handoff | Twelve fictional survey points exported from LifeJacket, imported into Legacy Mission Hub and saved privately. The pilot confirmed the route loaded on the iPhone. |
| DJI Fly video | Original Mini 2 camera reached the private Mac receiver over local Wi-Fi. A case frame was saved and reopened. Interruption and reconnection were observed. |
| Litchi video | After restoring the FPV camera view, the same receiver showed **Connected**, displayed a sampled preview and received fresh frames at 10:50:04 and 10:50:10 PM Chicago time. These are server reception times. |

All checks were motors-off. For the outdoor acceptance test, the pilot will
review a short route planned for the actual site. Verify that fresh frames
continue arriving while Litchi follows that route, record interruptions and
pilot takeover behavior, and measure camera-to-screen delay. Leave the fictional
ground-test mission as a rehearsal artifact. Aerial observation usefulness
requires its own review.

## Primary references

- [DJI Fly livestream operation](https://repair.dji.com/help/content?customId=en-us03400006727&lang=en&paperDocType=paper&re=US&spaceId=34)
- [Litchi connection, video sharing and mission sync](https://flylitchi.com/help)
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

Open the authenticated Workbench proxy for port 8935. The server is loopback-only and uses a disposable database, synthetic identity, a generated MP4 and a real RTMP receiver. Without `--phone-bind`, it seeds an approved, in-progress recorded-demo request so you can save frames and complete review. It never connects to production data or a drone. Stop this rehearsal before running receiver integration tests because it uses the same private media ports. Restart it to reset the synthetic case. The initial stream expires after 30 minutes; shutdown removes disposable data and stops its media children.


## Verification on 2026-11-07

- 55 backend checks passed, including the opt-in real MediaMTX/FFmpeg RTMP rehearsal with a generated MP4.
- 14 client API checks, TypeScript validation and Ruff passed.
- Browser rehearsal saved an exact displayed frame, ended the stream, submitted evidence for review, recorded still uncertain, and scheduled follow-up. Stream reception time remained separate from unknown camera capture time; the original case assessment was preserved.
- Bad publishing credentials, non-lead writes, unrelated case access, stale frames, expiry and loss of case participation are covered. The transport check verified interruption, reconnect and publisher disconnection on end. The receiver exits with its media children on termination.
- This software rehearsal preceded the November 24 Mini 2 ground checks.


See [drone_workflow_readiness.md](drone_workflow_readiness.md) for the latest coverage review and remaining software, deployment and hardware acceptance items.


Saved-frame AI jobs and closed-app reminder delivery are described in [drone_followup.md](drone_followup.md).


## Rehearsal setup boundaries

The rehearsal uses the actual coordinator request/stream/evidence UI and case APIs.
It is intentionally disposable: stopping it removes its generated media and test database.
Do not use it for real animal evidence. A deployed API, receiver and analysis worker must
share persistent database/evidence storage and the same configuration.

The live preview remains sampled. The optional received-video archive now adds private
segment playback; see [drone_recordings.md](drone_recordings.md). Without that flag, the
receiver retains selected stills only. Recorded-file selection separately copies
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
