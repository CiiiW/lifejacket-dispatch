# Public condition pilot and independent expert evaluation

This is a **development collection of unverified candidates**, not an injury
ground-truth dataset. No model training or rescue-case creation is performed.

The first snapshot contains 40 iNaturalist observations/photos, selected across
the chatbot's seven named animal groups plus unknown. Hints are inherited from
the existing identification evaluation taxa; they need review too. All photo
downloads succeeded. `pilot_v1/collection.json` records counts and exact queries.
`pilot_v1/candidates.jsonl` keeps source links, attribution, license codes, dates,
text/field evidence, community alive/dead annotations, mentions, hashes and blank
review templates. Images are stored locally in `pilot_v1/photos/` and ignored by git.

## Reproduce the saved sample

Use the project's backend environment (`pip install -r backend/requirements.txt`):

```bash
PYTHONPATH=backend python research/public_condition_pilot/collect.py --fetch-existing
```

This restores the exact selected images from the saved URLs and verifies their
SHA-256 hashes. It does not change the manifest, review fields or original sample.
If a remote image changes or becomes unavailable, restoration fails visibly;
it never replaces a saved case with a different photograph.

For a fresh collection, supply a new output directory:

```bash
PYTHONPATH=backend python research/public_condition_pilot/collect.py \
  --output research/public_condition_pilot/pilot_v2 --download --limit 40
```

Existing manifests cannot be overwritten. Requests are bounded and rate-limited.
The collector uses existing identification observations, a public morbidity
project, and condition-text searches within known taxa. It balances group hints,
limits each observer to two selected observations, and records duplicate photo
hashes. Query selection is opportunistic, not a representative prevalence sample.

## What labels mean

- `condition_mentions` records words in community descriptions, tags and
  condition-related observation fields. **Negated or speculative mentions are
  included**: "no bleeding" is still a bleeding mention, not a positive finding.
  Search results or project membership alone are not injury labels.
- Every medical review flag begins as `null`, with `condition_unknown: true`,
  `expert_reviewed: false`, and an unassigned development split. Alive does not
  mean healthy, and dead does not establish injury or cause of death. Blank fields
  do not become negative labels.
- Review the original image to mark visible signs as observed, absent in this
  view, or not assessable. A boolean false should mean not seen in the available
  view, not a confirmed absence of injury. Record uncertainty in `notes`.
- Keep confirmed clinical findings separate from visible image evidence. A
  wound, entanglement or posture can be reviewed from an appropriate image;
  hidden conditions cannot be established from a distant still.
- Record reviewer, qualification, review date, species/group, and viewpoint.
  Aerial performance is unknown until tested on actual aerial imagery.
- Store completed human reviews in a new versioned file keyed by `case_id`;
  preserve the original collection snapshot and source evidence.

## Source and reuse policy

- Public source: [iNaturalist API](https://api.inaturalist.org/v1/docs/).
- Candidate project: [Wildlife Diseases: Morbidity and Mortality](https://www.inaturalist.org/projects/wildlife-diseases-morbidity-and-mortality).
- Taxon seeds: `research/identification_eval/manifest.csv` (the original 102 cases).
- This pilot selects only photo license codes `cc0` and `cc-by`, retaining
  attribution and the source URL with each image. Original bytes are preserved.
  Do not assume public visibility alone grants reuse rights.
- Descriptions/tags/condition fields are retained only where the observation
  itself has a `cc0` or `cc-by` license. Other observation text is omitted.
  No precise observation coordinates or full user profiles are copied.
- Recheck rights and attribution before redistribution. The original license
  codes are retained without guessing the Creative Commons license version.

## NOAA evaluation sample

Ask the existing NOAA contact for a small expert-reviewed evaluation sample,
or an introduction to the relevant researcher/response partner. Request images
linked to assessments, including normal behavior, visible concerns, and uncertain
cases; aerial or distant views are especially useful. Ask for permitted evaluation,
training, demonstration and redistribution uses separately.

Reserve independent NOAA cases as a locked evaluation set. Do not add them to
training, prompt tuning, retrieval examples or this development collection.
Before evaluating, check observation IDs, photo hashes, animal/event identities,
and sequences for overlap with development data. Multiple frames or repeated
sightings from the same animal/event belong to the same split. Species-ID data
already used in development are marked `prior_identification_eval`.

An initial 20–50 reviewed cases can support a feasibility pilot and error review;
they do not establish broad accuracy across all groups. Report results and gaps
per group and visible concern, alongside false alerts and missed cases. No NOAA
evaluation data or expert injury annotations have been received yet.

Validation: all 352 offline backend tests passed, including license filtering,
uncertainty, group hints, negated text, original-byte preservation, hash mismatch
rejection and protection of existing review snapshots. Ruff passed for the collector
and its tests; all 40 downloaded image hashes were verified locally.

## Image-only baseline and private review

Run from the repository root with backend dependencies and Vertex ADC configured:

```bash
PYTHONPATH=backend python research/public_condition_pilot/run_baseline.py \
  --live --run-dir var/condition-baseline/pilot-v1 --resume
PYTHONPATH=backend python research/public_condition_pilot/run_baseline.py \
  --live --run-dir var/condition-baseline/pilot-v1 --serve --port 8813
```

The review server binds to **127.0.0.1**. On the authenticated GCP notebook,
open `/proxy/8813/`. Keep this behind notebook authentication; it has no separate
account system. It is a standalone research app and never creates dispatch cases.
Use `--limit 2` for a first live smoke run, then resume without a limit.
`--workers 3` bounds concurrency to three images (allowed range 1–4). A
`--dry-run` in a separate directory checks orchestration using scripted replies;
those outputs cannot measure quality and are excluded from comparison statistics.

Detection receives the original pixels after EXIF removal and orientation
normalization. Identification and assessment receive the selected crop. Neither
receives iNaturalist species, group hints, source descriptions, condition mentions,
or geographic context. A sole detection is analyzed but remains unconfirmed;
multiple detections pause for selection, and no detection is not a healthy label.
Draw a target to recover a miss. Tiny or degenerate targets fail explicitly.

Start by annotating the image with model suggestions and source context hidden.
Select **Yes** for an animal and draw its box; choose the shared chatbot animal
group, viewpoint and visibility. Each of six signs is **observed**, **not visible
in this view**, or **uncertain**. Defaults remain uncertain. Save a provisional
review before running analysis on a newly selected target. Model/source reveal
flags are retained. Your qualification is self-reported, never an expert stamp.
Source attribution remains visible throughout.

`run.json` records input, prompt/code hashes, model and settings. Per-image
predictions, every analysis attempt, current reviews and review revision history
are separate files outside the collection. Resume rejects changed fingerprints;
start a new run directory after a model, prompt, input or inference-code change.
Concurrent/stale edits return a conflict rather than overwrite another result.
Export includes the run metadata, current predictions, source provenance and
current reviews; histories stay on disk. Latest-attempt token/latency totals are
not a full billing ledger of retries or prior attempts.

Group-level sign comparisons require a provisional human review of the same
box and prediction version. Uncertain signs are excluded; exposure counts are
reported because these comparisons may be model-assisted. No clinical accuracy
is reported without independent expert ground truth. The public convenience
sample is not an aerial patrol benchmark. Keep future NOAA evaluation samples
held out from tuning, and separately evaluate detection misses, target selection,
viewpoint, and expert-reviewed signs.

First live run: [2026-10-23 results and limitations](BASELINE_RUN_2026-10-23.md).
