# YOLO → LifeJacket handoff, version 1

Owner split: the teammate trains/evaluates the detector; LifeJacket validates the output,
keeps evidence provenance, shortlists frames and sends selected stills into advisory
identification/condition assessment and deterministic triage. No whole video goes to Gemini.

## First integration boundary

Use an immutable saved evidence image, identified by `evidence_id` and SHA-256. The model
output contract is `lifejacket.models.drone_detector.DetectorFrameResult`; its JSON Schema
is in `config/drone_detector.schema.json`. The contract and coordinate adapter are now connected to authenticated case APIs and
the observation workspace. This does not install YOLO weights or an automatic detector worker.

Example with placeholder hashes (replace with actual file/weights hashes):

```json
{
  "schema_version": 1,
  "evidence_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "source_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "width": 640,
  "height": 360,
  "model_name": "lifejacket-detector",
  "model_version": "trial-1",
  "weights_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "source_kind": "sample_footage",
  "status": "completed",
  "detections": [
    {
      "class_name": "marine_mammal",
      "confidence": 0.8,
      "xyxy": [64, 36, 320, 180],
      "track_id": null
    }
  ],
  "error_code": null
}
```

`source_kind` uses existing evidence vocabulary: `sample_footage` or `operator_capture`.
Do not relabel a generated/example video as real operator footage.

## Coordinate and failure rules

- Coordinates are **pixel [xmin, ymin, xmax, ymax]** on the exact source image, after any
  agreed orientation normalization. Dimensions must match that image, not a resized model
  input. Undo detector resizing/letterboxing before output.
- `agent_detections()` converts to our existing **[ymin, xmin, ymax, xmax], 0–1000** convention.
  For the example above this is `[100, 100, 500, 500]`. Nonfinite, reversed and out-of-bounds
  coordinates are rejected rather than silently clamped. A subpixel box that collapses
  under normalization also requires review.
- `completed` with an empty list means successful inference with no detection. It does
  NOT mean no animal was present or the area was safe.
- `failed` requires an empty list and one error code: `decode_failed`, `inference_failed`
  or `model_unavailable`. It cannot be silently converted into an empty successful result.
- At most 32 candidates per frame. Preserve source confidence and class labels in the
  detector result; do not equate them with species-identification confidence or condition.
- Track IDs, if provided, are scoped to one run/connection. They do not establish that an
  animal is the same across flights, or that a second alert is a duplicate.
- No injury, urgency, GPS or capture-time fields are accepted from this detector contract.
  Those need their own verified inputs/review. Receiver time is not camera capture time.

The attachment service checks current case/evidence permissions, verifies the source file
hash/dimensions and provenance, and persists candidates/model metadata under an idempotent
job key. The Pydantic contract alone does not perform those checks; use the authenticated
endpoint, not a direct database insert. Model/weights names and hashes are declared provenance,
not independently validated detector quality.

## Integration/evaluation checklist for teammate

1. Return an example result and weights hash for the exact saved-frame dimensions.
2. Run on distinct held-out source videos, including empty/rock/wave scenes and multiple
   animals. Report missed animals, false detections and latency on intended hardware.
3. Preserve some periodic/manual frames when the detector finds nothing; avoid hiding
   all evidence behind an unvalidated detector threshold.
4. Feed bounded candidates to Python shortlisting, then selected original frames/crops
   to Gemini. Retain full-frame context and original media for coordinator review.
5. Keep prototype results advisory. For an existing case, attach evidence to that case.
   Automatic patrol alerts, identity tracking and duplicate merging require separate work.

## Software rehearsal results

The expanded real MediaMTX/FFmpeg acceptance test runs the SAME synthetic case through:

RTMP publishing → preview → exact saved-frame evidence → validated external-detector result
attachment → explicit selection of candidate 2 → identification/assessment agents → severity rules → recorded
human review, alongside private MP4 playback, interruption/reconnect and receiver restart.

The identification/assessment adapters render their real prompts, validate responses,
crop the chosen animal and apply actual severity rules. Model replies come from
ScriptedLLMClient; external detector output is a labeled fixture. All model calls
in that chain receive one image, not a video. The test checks that evidence remains linked
to the session/case, the review is audited, and the original intake is not overwritten.

The combined focused run passed **57 backend checks**, including this real transport
chain and the seven detector-contract cases. Ruff and whitespace checks passed.

This establishes software integration only. It is not live Gemini validation, a YOLO
accuracy test, real aerial evidence or Mini 2/iPhone acceptance. JupyterLab/GCP credentials
are not required for this rehearsal; they are needed for a later live-model validation
in the team's configured environment.

Run with development dependencies and official MediaMTX v1.21.3/FFmpeg installed:

```sh
MEDIAMTX_BINARY=/absolute/path/mediamtx FFMPEG_BINARY=/absolute/path/ffmpeg \
  python -m pytest backend/tests/test_drone_stream_receiver.py -o addopts='' -q
python -m pytest backend/tests/test_drone_detector.py -q
```

Without MEDIAMTX_BINARY the transport test is skipped, not evidence of a passed stream.


## Connected coordinator workflow

1. Open an existing case's observation workspace. Receive video and save a useful frame,
   or attach an original image. Keep recordings linked to the same observation session.
2. Open that photo. In **Use teammate detector results**, export the frame metadata and
   download the exact original image. These identify its hash, size and provenance.
3. The teammate runs their detector on that original image and returns JSON matching the
   schema. Choose the same saved frame, select the JSON, confirm the correspondence and
   select **Attach detector results**. No Gemini call occurs at attachment.
4. Select that completed detection and the intended animal, explicitly confirm AI analysis,
   then select **Assess selected animal**. The existing worker runs identification,
   condition assessment and deterministic severity rules on the selected crop.
5. Review the advisory finding alongside the original frame and received recording.
   Mark evidence ready, then record the human outcome: answered, still uncertain or
   escalation needed. This does not automatically change the original intake or dispatch.

Endpoints (all under `/network/cases/{case}/drone-requests/{request}`):

- `GET /evidence/{evidence}/detector-input`: permitted saved-image source metadata.
- `POST /evidence/{evidence}/detector-result`: `{revision, confirmed:true, request_key, result}`.
  Only an authorized lead coordinator can attach a result. Reusing an identical key/output
  is idempotent; changing the output under the same key is a conflict.
- Existing `/analysis` and selected-animal analysis endpoints continue the same evidence.

A failed import has no target for assessment. Successful empty results remain explicitly
uncertain; neither case means the animal is absent. Failed external inference must be
rerun upstream and attached with a new key; it is not silently retried as a Gemini detector.

The UI handoff deliberately works before the trained model or automatic runner exists.
It completes the EXISTING-CASE coordinator review path. Real-time YOLO execution,
automatic shortlisting of newly received frames, patrol case creation/duplicate tracking,
physical aircraft connectivity and live-model quality still require their own integration
or acceptance. Do not present this prototype as autonomous flight or automatic rescue.
