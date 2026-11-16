# Tested recommendation: keep DMD; make Gemini advisory

**The decisive result is tiny-animal retention. A Gemini negative must not delete a DMD candidate.** The practical default is offline, operator-reviewed evidence windows, with selective AI review and class-specific context checks.

Tested **205 video frames across7 sources**, grouped into **19 windows**, four new review modes, a mixed-scene probe and three tiny-seal presentation checks. **104 new requests; 3 unusable outputs.** Existing four-model detection scores and five animal-evidence policies were also compared.

## New workflow comparison

| Method | Positive anchors | Control flags | Median call |
|---|---:|---:|---:|
| Single whole | 13/13 | 0/5 | 4.04s |
| Single + native crops | 11/13 | 0/5 | 4.41s |
| Three whole frames | 12/13 | 0/5 | 6.41s |
| Three + native crops | 10/13 | 1/5 | 7.87s |

Three native-mode outputs were unusable under the response/evidence checks; they remain failures, not silent retries. The single-whole method used55,540 reported total tokens, single-native44,473, burst-whole50,530 and burst-native100,370. Token totals are not dollar-cost estimates. These are manually screened window/anchor diagnostics, **not recall, specificity or box accuracy**. All methods review the same fixed midpoint or first/midpoint/last samples. Native adds candidate crops. Single and burst outputs refer only to their reviewed frames.

## Tiny annotated aerial seals: the stress check that changes the decision

| Input presentation | Mammal-positive images | Uncertain | No | Failed |
|---|---:|---:|---:|---:|
| single_whole | 0/8 | 0 | 8 | 0 |
| single_native | 0/8 | 3 | 5 | 0 |
| tight_native | 0/8 | 5 | 3 | 0 |

These are8 positive NOAA images with14 reference boxes. Native uses detector proposals, not ground-truth crops. The tighter presentation changes padding, crop budget and resize together; upsampling adds no detail. Presence is scored, not localization. There is no matched-domain negative set.

## Detector choice

| Model, tiled + whole | Matched seal boxes /14 | Unmatched proposals |
|---|---:|---:|
| dmd | 10/14 | 23 |
| grounding_dino | 2/14 | 37 |
| yolo_world | 0/14 | 18 |
| yoloe26 | 6/14 | 86 |

DMD whole-frame-only matched 0/14 in that cached subset. Preserve tiling for small animals; faster whole-frame processing is not an equivalent replacement.

YOLO-World remains a context proposer rather than the animal detector. The prior class-specific context test retained19 person-display frames and15 vehicle-display frames in the ground regression, while rejecting23 inspected surf/rock proposals. Those are display diagnostics, not accuracy.

## Annotated person/vehicle comparison (cached)

| Model | Person matches /30 | Vehicle matches /6 | Extra person / vehicle proposals |
|---|---:|---:|---:|
| dmd | 11 | 0 | 1 / 0 |
| grounding_dino | 25 | 6 | 9 / 1 |
| yolo_world | 23 | 5 | 2 / 0 |
| yoloe26 | 19 | 4 | 3 / 1 |

Grounding DINO matched more context references, while YOLO-World produced fewer extra context proposals and was faster in the prior T4 benchmark. This small inspected subset does not establish generalization.

## Cached animal-gate policy tradeoffs

| Rule | Surf active frames /31 | Beach active frames /38 | Ground active frames /24 |
|---|---:|---:|---:|
| crop_only | 20 | 6 | 24 |
| scene_only | 20 | 6 | 24 |
| same_check_agreement | 20 | 6 | 24 |
| two_scene_checks | 7 | 0 | 18 |
| agreement_or_repeated | 20 | 6 | 24 |

These are state replays using identical prior model responses, not new inference or accuracy. More stringent rules can suppress ambiguous positives but also delay/drop useful animal evidence.

## Practical configuration

1. Retain tiled DMD animal candidates and the original video. Group evidence into short review windows; do not count windows as animals.
2. Use a whole-view advisory check on a representative frame. Add native crops for uncertainty or disagreement. A negative AI judgment does not erase detector evidence.
3. Present an unconfirmed review card. A reviewer confirms animal presence for a specific immutable frame.
4. Show person/vehicle boxes only for that confirmed frame, with class-specific context verification. Do not carry approval to another scene or unreviewed frame.
5. Keep live streaming, automatic alerts and domain fine-tuning as separate validation work.

Adaptive routing replay would require 25 calls for these19 windows and preserves 6 detector candidate windows that the used AI responses do not confirm. This is an offline replay, not a deployed adaptive timing test. On the shared165-frame subset, the prior per-frame configuration requires117 model requests versus19 for this adaptive replay; outputs and review granularity differ, so this is a request-count comparison, not a measured speedup.

## Timing, boundaries and remaining work

- Fresh6-frame T4 timing, full: median 0.234s; 4K subset median 0.235s. Two synchronized repeats after warm-up; source decode/loading excluded.
- Fresh6-frame T4 timing, full_plus_tiles: median 1.986s; 4K subset median 2.002s. Two synchronized repeats after warm-up; source decode/loading excluded.
- Whole and native burst modes were tested across an injected visual cut. Context is joined to animal evidence only within the same reviewed frame. This is not natural scene-cut validation.
- Cached policy replays show the latency/retention tradeoff of stricter agreement and repeated checks; all underlying responses remain the same.
- No independently annotated aerial marine-animal-plus-human/vehicle positive was found. Dog-human footage is an aerial proxy; the seal release is ground-level.
- No training or independent flight-level fine-tuning evaluation was performed. No live2FPS, identity tracking, app integration or deployment claim.

## Reproduce

practical_options_prepare_v1.py freezes inputs and selection; practical_options_review_v1.py runs the four modes; practical_options_timing_v1.py measures detector cost; cut/seal/tight probe scripts run the stress checks; practical_options_archive_v1.py audits and scores. Exact request images and media references are under ~/aerial-data/practical-options-v1. Reports, plans, decisions and cards are under research/aerial_detector/results/practical-options-v1. Notebook cells display cached results only.

## Publication note

Machine prefixes were replaced with CACHE_ROOT/REPO_ROOT, URL queries stripped, notebook outputs cleared and selected images recompressed. Historical audit flags describe the original local run, not a fresh media audit of this checkout.
