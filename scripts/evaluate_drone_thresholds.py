#!/usr/bin/env python3
"""Offline policy evaluation; never changes configuration or selects a cutoff."""

import argparse
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from lifejacket.services.drone_suggestions import suggest  # noqa: E402

THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99)


def validate(dataset):
    if dataset.get("dataset_kind") not in {"synthetic", "reviewed"}:
        raise ValueError("Declare dataset_kind synthetic or reviewed")
    rows = dataset.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Provide a nonempty cases list")
    ids = set()
    groups = {}
    for row in rows:
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("Case IDs must be present and unique")
        ids.add(case_id)
        if type(row.get("verification_needed")) is not bool:
            raise ValueError("Each case needs a boolean reviewer label")
        if row.get("split") not in {"validation", "test"}:
            raise ValueError("Declare validation or test split")
        group = row.get("animal_event_id")
        if not isinstance(group, str) or not group:
            raise ValueError("Group related reports with animal_event_id")
        if group in groups and groups[group] != row["split"]:
            raise ValueError("Related animal events cannot cross splits")
        groups[group] = row["split"]
        if dataset["dataset_kind"] == "reviewed" and not row.get("label_provenance"):
            raise ValueError("Reviewed cases need label provenance")
        if not isinstance(row.get("incident"), dict):
            raise ValueError("Each case needs structured incident evidence")
    return rows


def evaluate(dataset, thresholds=THRESHOLDS):
    rows = validate(dataset)
    metrics = []
    for threshold in thresholds:
        if (
            type(threshold) not in (float, int)
            or not math.isfinite(threshold)
            or not 0 < threshold <= 1
        ):
            raise ValueError("Threshold must be finite and in (0,1]")
        for split in ("validation", "test"):
            selected = [r for r in rows if r["split"] == split]
            if not selected:
                continue
            tp = fp = fn = tn = urgent = 0
            for row in selected:
                incident = SimpleNamespace(
                    **{
                        "status": "awaiting_dispatch",
                        "duplicate_of": None,
                        "identification_json": None,
                        "assessment_json": None,
                        "latitude": None,
                        "longitude": None,
                        "severity_level": "monitor",
                        "entanglement_present": False,
                        **row["incident"],
                    }
                )
                result = suggest(incident, threshold)
                predicted = result is not None
                label = row["verification_needed"]
                tp += predicted and label
                fp += predicted and not label
                fn += not predicted and label
                tn += not predicted and not label
                urgent += bool(result and result["urgent_parallel_review"])
            metrics.append(
                {
                    "split": split,
                    "threshold": threshold,
                    "n": len(selected),
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "tn": tn,
                    "precision": tp / (tp + fp) if tp + fp else None,
                    "recall": tp / (tp + fn) if tp + fn else None,
                    "false_positive_rate": fp / (fp + tn) if fp + tn else None,
                    "suggestion_rate": (tp + fp) / len(selected),
                    "urgent_parallel_suggestions": urgent,
                }
            )
    return {
        "dataset_kind": dataset["dataset_kind"],
        "case_count": len(rows),
        "threshold_is_validated": False,
        "configuration_changed": False,
        "interpretation": (
            "Synthetic policy checks only; no evidence of real-world model accuracy."
            if dataset["dataset_kind"] == "synthetic"
            else "Descriptive reviewer-label evaluation. Validate sampling, labels and "
            "held-out performance before adopting a cutoff."
        ),
        "metrics": metrics,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=Path("data/evaluation/drone_threshold_synthetic.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("var/drone-threshold-evaluation.json")
    )
    args = parser.parse_args()
    result = evaluate(json.loads(args.input.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        f"Evaluated {result['case_count']} {result['dataset_kind']} cases; "
        "configuration unchanged."
    )
    print(args.output)


if __name__ == "__main__":
    main()
