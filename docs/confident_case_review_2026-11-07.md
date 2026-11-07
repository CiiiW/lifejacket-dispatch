# Four confident disagreements: source audit and fresh recheck

Date: 2026-11-07. This is a targeted failure analysis of four known development-set disagreements, not a random sample, held-out accuracy estimate or expert clinical review.

## Main findings

- All four manifest photo IDs remain attached to the listed iNaturalist observations. Current source taxa agree with the reference species, including subspecies. No photo-to-observation mismatch was found.
- The assistant visual audit finds three skull/remains-only views and one partly submerged head/snout. This audit is non-expert and was performed with labels visible; it is not new independent ground truth.
- Fresh full-image calls still disagree with the reference species in all four cases, at pooled routing-group confidence of 90–100%. None produces a low-confidence verification suggestion at the current strict-below-90% rule.
- Current detection returns no target for two skull photos and one target each for the other skull and the submerged animal. No-detection is not a healthy/no-action label; target choice remains a review problem.
- Both cropped outputs match the reference routing group, but neither matches the reference species: sea-otter remains are called a sponge, and the source-labeled manatee is still called an alligator. Group agreement alone would conceal these failures.
- The cropped submerged-view output asks for a new photo, but the current numeric/group suggestion rule does not surface a verification suggestion because the group score is exactly 90%. This is an explicit image-adequacy gap.

## Per-case findings

| Source reference / view | Full-image result | Detection path | Crop result |
|---|---|---|---|
| [Eumetopias jubatus](https://www.inaturalist.org/observations/264136175) — Skull/jaw on stones with a person nearby; remains-only view. | Ursus maritimus · terrestrial · 95% | 0 target(s) | Not run: no detector target |
| [Odobenus rosmarus](https://www.inaturalist.org/observations/6659273) — Weathered skull on the ground; remains-only view. | Eschrichtius robustus · cetacean · 90% | 0 target(s) | Not run: no detector target |
| [Enhydra lutris](https://www.inaturalist.org/observations/127403691) — Purple-stained skull on the ground; remains-only view. | Ursus arctos · terrestrial · 90% | 1 target(s) | Porifera · other_marine · 95% |
| [Trichechus manatus](https://www.inaturalist.org/observations/37589411) — Partly submerged head/snout with limited visible anatomy. | Alligator mississippiensis · terrestrial · 100% | 1 target(s) | Alligator mississippiensis · other_marine · 90% |

## What the results support

1. Separate remains/carcass and live-animal monitoring evaluation strata. Keep these hard cases in the benchmark with clear tags; do not remove them to improve the headline score.
2. Review source labels, image adequacy and target selection before treating a confident identification as reliable. The current detector handles remains inconsistently in this small audit.
3. Treat an explicit needs_new_photo/insufficient-view flag as a candidate for coordinator verification review even when a numeric score is high. This follow-up change is not implemented by this research recheck.
4. Check species–routing-group consistency. The cropped submerged-view prediction labels an alligator as other_marine, which happens to agree with the manatee reference group.
5. Do not tune or validate the threshold on these four preselected failures. A future representative, independently labeled set is still required.

## Run method and limits

- Current configured model: `gemini-2.5-flash`. Live run: 2026-11-07T22:05:58.352500+00:00 to 2026-11-07T22:07:06.885393+00:00.
- Four full-image identification calls, four detection calls and two cropped identification calls were made. Standard provider retries/usage are retained in the raw metrics. No condition-assessment calls were made.
- Current repository identification/detection agents and prompt files were used, with temperature 0.1. Each call is stateless. Species labels, source descriptions and location were withheld. EXIF was removed; image IDs are content-hash fragments.
- Detection/cropping was tested as a diagnostic path. A sole target was used automatically; it is not an expert-confirmed target. Multiple or absent detections are never silently resolved.
- Original downloaded bytes, prepared JPEGs, crop bytes, prompt/code files and run outputs have SHA-256 fingerprints. The exact runner used is preserved as runner_at_run.py in the local run directory.
- Source photo URLs match the saved manifest, but original October image hashes are unavailable. This is a fresh source retrieval, not a proven byte-identical historical replay. Current prompts and source context also differ from the October run.
- No real incident, drone request, flight, model training or expert condition label was created. The 90% setting is unchanged.

## Source/reuse notes

The preview remains behind authenticated notebook access. Original images and crops are not committed to git or published. Attribution and the manifest license codes are retained below. Three photos are CC BY-NC, so they are not added to a commercial/public demo bundle.

- eumetopias_jubatus_02: (c) IanLJones, some rights reserved (CC BY-NC) — cc-by-nc; source quality grade: research.
- odobenus_rosmarus_01: (c) Donna Pomeroy, some rights reserved (CC BY-NC) — cc-by-nc; source quality grade: research.
- enhydra_lutris_02: no rights reserved — cc0; source quality grade: research.
- trichechus_manatus_01: (c) Janet Wright, some rights reserved (CC BY-NC) — cc-by-nc; source quality grade: research.

## Reproduce

`python scripts/review_confident_cases.py --input-dir var/confident-case-review-2026-11-07` verifies the saved inputs without model calls.

Use a new run directory containing a verified source_audit.json and its source images, then pass `--live` for a fresh run. Existing live prediction files are protected from overwrite.


## Subsequent policy fix

The historical live-run outputs above remain unchanged. Policy low-confidence-v3
now turns an explicit `needs_new_photo: true` into a qualitative verification
suggestion even with sufficient numeric confidence. A no-new-inference replay of
the saved submerged-view crop is recorded in
`research/drone_validation/photo_gap_replay_2026-11-07.json`. This changes the
suggestion outcome, not the saved model identification or its validity.
