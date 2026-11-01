# NOAA wildlife video pilot — 2026-10-31

GCP Vertex inference completed: **12 frames, 0 failures**. This checks the
processing path, not recognition accuracy, injury diagnosis or distinct animals.

## Source and credit

[NOAA Fisheries California Sea Lions B-roll](https://videos.fisheries.noaa.gov/detail/videos/b-roll-packages---all/video/4084857759001/b-roll%3A-california-sea-lions),
video ID `4084857759001`. The gallery permits public-domain B-roll reuse with
credit; sequence slates specify further attribution/permit information.

Inspected general and opening Point Bennett slates: credit NOAA Fisheries;
cinematography Paul B. Hillman / NOAA Fisheries; filmed under NMFS MMPA Permit
#16087-01 and #14327. Retain credits with the opening excerpt. Inspect other
sequence slates before using later portions; these are not our filming permits.
Location is described as Point Bennett, San Miguel Island, Channel Islands
National Park, California. Capture date and animal GPS are unknown.

Original MP4: 152,764,205 bytes, 1280×720, duration 311.786667 seconds.
SHA-256: `f335b21c54e45cc2689bee64715cc12f7acf6338ca8016ff0c9c08941cbcc541`.
Original and all extracted frame hashes verified on GCP.

## Run and observations

- GCP worktree `/home/jupyter/lifejacket-mini2`, branch `charlotte-mini2-demo`.
- Bundle: `var/mini2/noaa-sealion-opening-credited`; first 12 samples about 2s apart.
- Offsets: 0, 2.002, 4.004, 6.006, 8.008, 10.010, 12.012, 14.014, 16.016,
  18.018, 20.020 and 22.022 seconds. This is only the opening section of the file.
- GCP manifest SHA-256:
  `c1b1d85a8626c8e4d4e62b52e0cd2e3e2701ed882e2cd00cef044fc91043a768`.
- Model: `gemini-2.5-flash`, existing DetectionAgent, one attempt per frame.
- 12 completed, 0 failures; 32,784 prompt tokens, 806 output tokens;
  summed saved per-frame latency 46.38 seconds (not wall-clock end-to-end latency).
- Boxes per frame: **0, 0, 0, 0, 0, 0, 0, 0, 1, 3, 4, 5**.
- Five opening credit/slate samples returned no candidates. The next three
  aerial-view samples also returned none; no absence-of-animals claim follows.
- Later descriptions refer to groups/colonies of mammals. The 13 candidate
  boxes are **regions containing possible groups**, not 13 individual animals.
  They are not human-validated targets or distinct sightings. No expert labels.
- Browser review page loaded all frame summaries. Coordinates and capture time
  remain unknown. No real app observations, cases or notifications created.

[Saved detection output](../research/noaa_video_pilot/gcp-detections-2026-10-31.json)
records boxes, descriptions and actual attempt metrics. Media stays in ignored
`var/`; no source video or frames committed.

## Reproduce

Download the original MP4 from the official source page (refresh the page for an
unexpired download link) and verify the hash above. Do not save temporary signed
CDN URLs in git. Put it at `var/mini2/noaa-california-sea-lions.mp4`.

```bash
export PATH="$PWD/var/ffmpeg-env/bin:$PATH" # GCP's isolated FFmpeg
PYTHONPATH=backend .venv/bin/python scripts/drone_video.py prepare \
  var/mini2/noaa-california-sea-lions.mp4 \
  --metadata config/examples/noaa_sealion_video_metadata.json \
  --output var/mini2/noaa-new-attempt --interval 2 --max-frames 12
PYTHONPATH=backend .venv/bin/python scripts/drone_video.py detect \
  var/mini2/noaa-new-attempt
```

A new manifest hash may result from changed metadata/decoder version. Detection
results fingerprint their own manifest and must never be attached to another.
Existing bundles/results are immutable; use a fresh output for another attempt.
GCP ADC was refreshed successfully; no user credential export is required.

Private review is served only from this bundle, bound to 127.0.0.1:8917 and
reachable through authenticated notebook `/proxy/8917/review.html` while running.

## Next validation

Manually label a short continuous, closer-view sequence, including missed
animals and empty-scene controls. The current wide colony views are unsuitable
for asserting individual identity or assessing injury. Review detection boxes,
misses, crowded-group handling and camera/shot changes before any tracking score.

Keep `wildlife_recording` provenance; the toy/synthetic app queue intentionally
rejects this bundle. Do not relabel real animals as demo fixtures. Real-wildlife
video app review and independently labeled aerial/injury evaluation remain work.


## Overlay and worksheet follow-up

The same saved predictions now render as 13 numbered region boxes on the private
review page. No model rerun was needed. A portable
[provisional review example](../research/noaa_video_pilot/provisional-slate-review-2026-10-31.json)
marks only the opening credit slate as reviewed (no animals visible); the remaining
11 frames are explicitly unreviewed. Missed count is unknown/null, not zero.
This is a Codex visual project review with model output exposed, not independent
expert ground truth. It does not establish detection recall or injury accuracy.
See the [worksheet workflow](mini2_demo.md#inspect-boxes-and-record-provisional-reviews).
