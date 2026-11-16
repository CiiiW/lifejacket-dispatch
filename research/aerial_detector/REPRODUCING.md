# Reproduce and inspect the research

## Offline snapshot checks

From this repository root, run:

    python research/aerial_detector/validate_snapshot.py
    python -m compileall -q research/aerial_detector

No GPU, network, API credentials or model calls are needed for snapshot validation. The published notebooks read committed reports and display relative assets. Their numeric tables are Markdown.

publication_manifest.json records publication-file hashes, original experiment-code hashes and asset credits. Validation checks those hashes, result counts, retained failures, source selections, notebook stripping and link targets. It is not independent reproduction of model accuracy.

## Optional environments

Use a separate Python3.10+ environment, preferably3.11 for the shared backend client. Base DMD dependencies are in requirements.txt; optional comparison/API dependencies are in requirements-benchmark.txt. Match PyTorch/CUDA to the machine. Recorded versions are in results/ENVIRONMENTS.json.

The historical Gemini helper imports the repository backend client/config. Configure credentials through the existing backend environment instructions. Never put them in notebooks, result files, Git URLs or commits. No credentials are included here.

## External cache and media

Videos/images, checkpoints, environments and training runs are not committed. Sources/hashes are in results/SOURCES.json and results/model-comparison-v1/input-plan.json. Acquire media under its provider terms and preserve attribution; selected derivatives have assets/CREDITS.json.

Historical drivers normally use $HOME/aerial-data/<study>/ for caches and resolve code from __file__. Public machine paths are replaced with CACHE_ROOT or REPO_ROOT. Materialize those placeholders in a local cache outside Git and restore original media/checkpoints with matching hashes. Missing media is not a negative detection.

Experiment sequence:
1. model_compare_* freezes/scans the small reference cohort and compares models.
2. combined_* runs the ground-release paired check.
3. aerial_patrol_* and aerial_control_prepare_v1.py acquire/screen aerial examples.
4. context_video_* runs full-clip reviews. context_ground_scope_correction_v1.py restricts the mixed reference file to24 actual release samples before scoring.
5. practical_options_* compares single/burst whole/native modes and stress checks.
6. review_card_guard_v1.py keeps approval frame-specific and hides unconfirmed context.

The final trial also consumes prior cached dog-human and parking-control observations. Their media provenance is catalogued; caches are not embedded. Reconstruct observations using the detector settings, or use committed snapshots to reproduce tables without pretending to rerun inference.

Fresh model/data reproduction requires the external cache and original stage inputs. This package does NOT claim a one-command fresh-data benchmark. Drivers are archived recipes; assertions prevent accidentally overwriting completed paid runs.

## Reporting limits

- Previously inspected development cohorts. Window anchor counts are not recall/specificity, and display-frame counts are not independent box accuracy.
- Tiny-seal stress:8 positive images/14 references, no matched-domain negatives.
- Three unusable native-mode outputs were not silently retried.
- Adaptive routing was replayed from real cached responses.19 versus117 requests is not a live-speed claim.
- Human confirmation belongs to one immutable frame, not another scene.
- No fine-tuning, live2FPS, identity tracking, app integration or autonomous dispatch was validated.
