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

## Completed opening review and closer-view follow-up

The [complete opening review](../research/noaa_video_pilot/provisional-opening-review-2026-10-31.json)
adds a provisional assessment for all 12 original frames, superseding the initial
one-slate worksheet as the latest review. It preserves the earlier export.

- 5 slates: no animals visible, no predicted regions, missed count 0.
- 4 wide aerial frames: animal presence uncertain, missed count unknown/null.
- 3 later aerial frames: visible colony areas; individual counts remain unknown.
- Of 13 model-proposed regions, 5 are marked possible groups and 8 uncertain.
  No individual identity, expert injury or accuracy labels are implied.
- Reviewer: Codex visual review; model-visible and not independent ground truth.
  Presence/region judgements cannot substitute for per-target reference boxes.

### Closer-view inference

Scouted the original package at 10-second intervals (32 samples, no model calls)
and selected a closer-view Point Bennett sequence. The new excerpt contains two
foreground pups and cropped/background animals early on; one pup leaves later.
This is ground-level footage, not an aerial benchmark. An animal leaving the
frame is not a missed detection. Define treatment of partial/background animals
before labeling recall.

An 8-second excerpt was re-encoded with source `trim` and zero-based output PTS.
First/last retained parent PTS reported by FFmpeg: **156.023 / 163.997 seconds**.
Both parent and excerpt hashes are preserved in
[parent provenance](../research/noaa_video_pilot/pups-close-parent-provenance-2026-10-31.json).
Capture date, GPS, aircraft position and animal location remain unknown.

GCP bundle: `var/mini2/noaa-pups-close-156s`. Private review:
notebook `/proxy/8919/review.html`. Model: existing Gemini 2.5 Flash DetectionAgent.

- 16 samples at roughly 0.5-second intervals, offsets 0–7.508s relative to excerpt.
- 16 completed; 0 failures. Boxes per frame:
  **2,2,2,3,3,3,3,2,2,2,2,2,1,1,1,1**.
- 32 region proposals across repeated frames, not 32 distinct animals.
- Saved attempt latency sums to 80.14s; token total 45,333 (not a cost estimate).
- Browser verified all 16 images and 32 overlays. The 4.004s/4.505s views show
  separate proposals around the two visible pups. Individual reference boxes
  and full candidate reviews for this new excerpt remain pending.
- [Detection output](../research/noaa_video_pilot/pups-close-detections-2026-10-31.json)
  and [manifest](../research/noaa_video_pilot/pups-close-manifest-2026-10-31.json)
  retain hashes, offsets and attempt metrics. No cases/notifications created.

Reproduce after restoring the original MP4 and verifying its hash above:

```bash
ffmpeg -nostdin -v info -i var/mini2/noaa-california-sea-lions.mp4 \
  -vf 'trim=start=156:duration=8,showinfo,setpts=PTS-STARTPTS' \
  -an -c:v mpeg4 -q:v 2 -threads 1 var/mini2/noaa-pups-156-164.mp4
PYTHONPATH=backend python scripts/drone_video.py prepare \
  var/mini2/noaa-pups-156-164.mp4 \
  --metadata config/examples/noaa_pups_excerpt_metadata.json \
  --output var/mini2/noaa-pups-new-attempt --interval 0.5 --max-frames 16
PYTHONPATH=backend python scripts/drone_video.py detect var/mini2/noaa-pups-new-attempt
```

Use fresh paths; do not overwrite evidence. Decoder/encoder changes may change
hashes and sample timing; retain newly observed provenance rather than copying
this run's hashes. Keep the general/sequence credits with any excerpt.
