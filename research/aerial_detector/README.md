# Drone detection research: candidate evidence before automation

**Start with [REPORT.md](REPORT.md) or [notebook20](notebooks/20_practical_options_report.ipynb).**

This package compares four detector models, five cached animal-gate rules and four newly run review workflows. It contains research code and compact development evidence. No backend or client imports this package.

## Recommendation

Keep tiled DroneMegaDetector animal proposals and YOLO-World person/vehicle proposals. Group recorded-video evidence into short review windows. Gemini is advisory; its negative answer must not delete a detector candidate. Show context only after animal confirmation for that same frame and class-specific context verification.

The decisive small-animal check contained8 annotated positive NOAA images (14 seal boxes): none of the tested Gemini presentations confirmed a mammal. This is a previously inspected development stress check, not population accuracy.

## Tested scope

- Four-model comparison: DMD, Grounding DINO, YOLO-World, YOLOE;8 NOAA images/14 animal boxes and8 COCO images/30 person +6 vehicle references.
- Practical workflows:205 sampled frames from7 sources,19 review windows, four image/crop/temporal modes.
- Mixed-scene probe and three tiny-seal presentations.
-104 new model requests;3 unusable native-mode outputs retained as failures.
- Five cached animal-gate rule replays; synchronized six-frame T4 timing diagnostic.

There is no independent aerial marine-animal-plus-human/vehicle positive. The dog-human clip is a non-marine proxy and the seal-release retention check is ground-level. Fine-tuning, live DJI streaming and field generalization were not validated.

## Read the evidence

| Entry | Purpose |
|---|---|
| [REPORT.md](REPORT.md) | Final decision, methods and limits |
| [16](notebooks/16_alternative_detector_comparison.ipynb) | Four detectors |
| [17](notebooks/17_combined_detector_gemini.ipynb) | Ground-level paired smoke test |
| [18](notebooks/18_aerial_patrol_validation.ipynb) | Aerial clips and error examples |
| [19](notebooks/19_context_verified_video.ipynb) | Complete-clip context-verifier A/B |
| [20](notebooks/20_practical_options_report.ipynb) | Practical alternatives and recommendation |
| [results](results/) | Sanitized summaries, decisions and CSV tables |
| [assets](assets/) | Selected attributed image derivatives |
| [REPRODUCING.md](REPRODUCING.md) | Offline checks and optional research reruns |

This research-only PR does not enable a detector, change production prompts, integrate an app workflow, or configure incidents, flight control or dispatch. Historical experiment drivers are preserved to match their executed-code hashes. They require external caches; they are not a turnkey service.
