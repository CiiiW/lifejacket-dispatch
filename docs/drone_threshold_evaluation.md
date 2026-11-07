# Drone confidence threshold evaluation

The 90% cutoff remains provisional. The runner never updates configuration.

## Current run

Twelve hand-authored synthetic policy scenarios were evaluated. These cases exercise routing-group pooling, low condition confidence, missing or invalid scores, unidentified animals, urgent parallel review, duplicate reports and closed cases. They are not representative wildlife observations, calibrated model probabilities, expert labels or evidence of real-world accuracy.

All current examples are in the validation split; there is no held-out test set. The table is a policy smoke check, not a cutoff-selection result.

| Cutoff | Suggestions | Expected positives found | Expected positives missed | Unexpected suggestions |
|---|---:|---:|---:|---:|
| 50% | 1/12 | 1 | 4 | 0 |
| 60% | 2/12 | 2 | 3 | 0 |
| 70% | 4/12 | 4 | 1 | 0 |
| 80% | 4/12 | 4 | 1 | 0 |
| 85% | 4/12 | 4 | 1 | 0 |
| 90% | 5/12 | 5 | 0 | 0 |
| 95% | 6/12 | 5 | 0 | 1 |
| 99% | 8/12 | 5 | 0 | 3 |

## Run on reviewer-labeled cases

Run from the repository root:

`python scripts/evaluate_drone_thresholds.py --input your_cases.json --output var/threshold-review.json`

Use the synthetic JSON file as a schema example. For actual cases set `dataset_kind` to `reviewed`. Every case requires a boolean `verification_needed` label, label provenance, case ID, animal event ID, validation/test split and structured incident evidence. Labels should answer whether an additional observation would help the coordinator, separately from flight feasibility and medical urgency.

Group repeated reports of the same animal event into one split. Sample clear and unclear intake, poor images, different routing groups, monitoring cases and urgent cases. Have qualified reviewers adjudicate disagreements before evaluation. Choose any candidate cutoff using the validation set, then assess it once on the held-out test set using `--test-threshold CHOSEN_CUTOFF`. By default the runner reports validation results only. It never sweeps multiple cutoffs on held-out cases.

The runner reports confusion counts, precision, recall, false-positive rate, suggestion rate and urgent parallel suggestions by split. It rejects absent labels/provenance, duplicate IDs and animal-event leakage across splits. No threshold is marked validated automatically. Review false negatives and workload with the response partner before changing the configured threshold.
