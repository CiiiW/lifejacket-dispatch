# Mini 2 demo: work before the aircraft arrives

Working branch: `charlotte-mini2-demo`, based on main `3a323e9`.

Goal: a reviewed preset flight, video sampled on the laptop, an animal-shaped
candidate and image/time/location evidence for human review. Toy detections are
not injury diagnoses. No real rescue messages or case creation in this path.

## What works now

A local CLI copies and hashes the original recorded video, extracts a bounded
JPEG sample with source presentation-time offsets, and generates `review.html`.
Optional detection uses the existing animal DetectionAgent (same downstream
identification/taxonomy path as photos); it does not introduce a separate species
list. Results and per-frame failures are saved in the bundle. Toy/synthetic bundles can
also be imported into a separate demo review table; they never become incidents.
The existing detector is trained/prompted for real animals; recognition of a
particular toy must be tested and may fail. No recognition accuracy is claimed.

Limits: local MP4/MOV/MKV only, 1 GB, 10 minutes, up to 8192 pixels per axis and
40 million pixels per frame, output max edge 1280 pixels, 1–60 sampled frames,
interval 0.5–60 seconds. Default: first 12 samples about 2 seconds apart.
Reaching the sample cap does not mean the whole clip was inspected. Sparse
sampling can miss short appearances. Evidence bundles cannot be overwritten.

## Run on your laptop

Install Python 3.11+ and FFmpeg (`ffmpeg` and `ffprobe` on PATH). For macOS with
Homebrew, `brew install ffmpeg`. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-staging.txt
mkdir -p var/mini2
cp config/examples/mini2_video_metadata.json var/mini2/metadata.json
```

Edit the copied JSON to record actual ownership/permission and source. If known,
set `recording_started_at` to the recording START time with timezone, for example
`2026-10-31T14:00:00-05:00`. Otherwise leave null: only clip-relative times will
be shown. Do not substitute the upload time. This value is operator supplied,
not verified from the aircraft or guaranteed to be synchronized with telemetry.

```bash
PYTHONPATH=backend python scripts/drone_video.py prepare /absolute/path/clip.mp4 \
  --metadata var/mini2/metadata.json --output var/mini2/clip-001 \
  --interval 2 --max-frames 12
```

Open `var/mini2/clip-001/review.html` in a browser. It needs no server, database,
model credentials or drone. `manifest.json` records SHA-256 hashes, extraction
settings, decoder version, timestamps, provenance and unknown location fields.
Original video and all private outputs belong under Git-ignored `var/`.

After reviewing frame count and evidence, optionally run the real detector:

```bash
# Uses existing Google ADC/project access and consumes Vertex model quota.
PYTHONPATH=backend python scripts/drone_video.py detect var/mini2/clip-001
```

This sends sampled images to the existing configured Vertex model. It never
uploads the entire video. Review the refreshed HTML and `detections.json`.
An empty detection list is distinct from model failure and does not establish
that no animal was present. The command exits nonzero if a frame failed.
The detection output fingerprints its source manifest. Prepare a new bundle
if rerunning; do not alter old evidence or mix different attempts silently.

## Validation and next work

1. Test photos/phone recordings of the actual toy, including empty-scene clips,
   different viewing angles and a target small in the frame.
2. Run a permitted real clip through preparation and, when credentials are
   available, detection. Review misses and false positives manually.
3. Add repeated-sighting grouping with uncertainty; frames are not distinct
   animals and candidate counts must not be summed as animal counts.
4. Use the implemented Demo review tab for toy/synthetic frames. Real wildlife
   video review remains future work; existing observation contracts are
   California-scoped. Do not fabricate coordinates or mark toys as real.
5. Test Mini 2 + controller + iPhone/Litchi connection and live RTMP reception.
   This importer is recorded-file-only, not an implemented RTMP receiver.
6. Export aircraft GPS logs, verify their format/time basis, and measure video
   delay before aligning positions. Until then both position fields remain null.
   Aircraft position is not animal position. No invented uncertainty radius.
7. Physical flight only after independent operator/site readiness, route review
   and link/failsafe checks. Existing SITL endpoints remain simulator-only.

Litchi routes/video streaming are the proposed hardware path, not verified on
our devices. This path has no external AI-to-Litchi flight-control integration.
No Pi is required for the proposed Mini 2 camera path.

## Check the implementation offline

```bash
pip install pytest
PYTHONPATH=backend pytest backend/tests/test_drone_video.py
```

Tests decode generated video, verify actual timestamps/hashes, bound sampling,
reject damaged media, preserve timezone/unknown time, escape review text and
exercise the detection agent with scripted responses, including failures and
integrity rejection. These are workflow checks, not animal-detection evaluation.
A real aerial/toy clip and live model run are still outstanding.

## GCP working environment (2026-10-31)

Checkout: `/home/jupyter/lifejacket-mini2`, branch `charlotte-mini2-demo`.
Python 3.11 environment: `.venv`. FFmpeg 6.1.2 is isolated under ignored
`var/ffmpeg-env` because the system Debian mirror returned package 404s.
Before preparing video or running decoder tests in a new terminal:

```bash
cd /home/jupyter/lifejacket-mini2
export PATH="$PWD/var/ffmpeg-env/bin:$PATH"
```

Generated check bundle: `var/mini2/synthetic-camera-check`.
This is a six-second test pattern, not animal or drone evidence.
Review server is bound to 127.0.0.1:8914 and reachable through the authenticated
Jupyter proxy at `/proxy/8914/review.html` while the server/instance is running.
It serves only the generated bundle; it does not expose other repository files.

GCP validation: 375 backend tests passed with 13 decoder tests initially skipped;
the 13 decoder tests subsequently passed separately after installing FFmpeg.
No live model evaluation or actual toy/aerial video has been run.

## Demo-only app review

Set `DRONE_DEMO_ENABLED=true` only in a private demo environment. It defaults to
false. The importer accepts only `toy_demo` and `synthetic_test` bundles, validates
the entire bundle and hashes before uploading, and uses a loopback HTTP API.
Do not edit immutable bundle metadata; import a new preparation when it changes.
Identical imports preserve existing reviews; conflicting metadata returns 409.
A network failure can leave a partial import: rerun the same command to resume.

For a private combined console/demo API preview, build from the repository root:

```bash
cd clients/responder_console
npm ci
EXPO_PUBLIC_API_URL=./api npx expo export --platform web --clear
cd ../..
DRONE_DEMO_ENABLED=true \
DATABASE_URL=sqlite:///./var/mini2/demo-review.db \
DRONE_DEMO_DIR=var/mini2/queue-evidence \
PYTHONPATH=backend python scripts/serve_drone_demo.py --port 8915
```

In another terminal:

```bash
PYTHONPATH=backend python scripts/import_drone_demo.py var/mini2/clip-001 \
  --api-url http://127.0.0.1:8915/api
```

Open `/proxy/8915/` on the authenticated GCP notebook, then **Demo review**.
The preview exposes only the demo API; other console tabs require the full
backend and are not served by this preview. Select a frame, enter reviewer/name
and a note, then keep or reject it. Reviews retain history and reject stale edits.
Capture time can be unknown; aircraft/animal coordinates are always unknown in
this demo contract. Frames and candidates are not counts of distinct animals.

This preview binds to loopback and relies on the notebook proxy for access;
there is no app-level authentication. Do not expose it publicly. It uses a
separate database and evidence directory and cannot create rescue cases or send
notifications. Uploaded files are bounded JPEG frames, not whole videos.
