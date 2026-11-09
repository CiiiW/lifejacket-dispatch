#!/usr/bin/env python3
"""Retrospective saved-prediction analysis. No network, training or live cases."""

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from lifejacket.services.drone_suggestions import (  # noqa: E402
    GROUPS,
    group_confidence,
    score,
    suggest,
)

THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pooled_prediction(identity):
    confidence = group_confidence(identity)
    if confidence is None:
        return None, None
    totals = defaultdict(float)
    for candidate in identity.get("candidates", []):
        if candidate.get("animal_group") in GROUPS:
            totals[candidate["animal_group"]] += candidate["confidence"]
    if not totals:
        return None, confidence
    winners = [
        key for key, value in totals.items() if abs(value - max(totals.values())) < 1e-10
    ]
    return winners[0] if len(winners) == 1 else None, confidence


def identification_analysis(manifest, raw):
    references = {r["case_id"]: r for r in csv.DictReader(manifest.open())}
    rows = [json.loads(line) for line in raw.read_text().splitlines() if line.strip()]
    rows = [r for r in rows if r.get("variant_type") == "original"]
    ids = [r["case_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Repeated original predictions; select a single saved run")
    if set(ids) != set(references):
        raise ValueError("Prediction/reference cases do not match")
    results = []
    errors = 0
    for row in rows:
        if row.get("error"):
            errors += 1
            continue
        identity = row.get("response") or {}
        predicted, confidence = pooled_prediction(identity)
        ref = references[row["case_id"]]
        results.append(
            {
                "case_id": row["case_id"],
                "reference_group": ref["animal_group"],
                "predicted_group": predicted,
                "group_confidence": confidence,
                "group_agrees": predicted == ref["animal_group"],
                "reference_species": ref["species_scientific"],
                "source_url": ref["observation_url"],
                "identity": identity,
            }
        )
    known = [r for r in results if r["reference_group"] in GROUPS]
    per_group = []
    for group in sorted({r["reference_group"] for r in results}):
        selected = [r for r in results if r["reference_group"] == group]
        per_group.append(
            {
                "group": group,
                "n": len(selected),
                "agreement_count": sum(r["group_agrees"] for r in selected),
            }
        )
    sweep = []
    for threshold in THRESHOLDS:
        high = [
            r
            for r in known
            if r["group_confidence"] is not None and r["group_confidence"] >= threshold
        ]
        low = [
            r
            for r in known
            if r["group_confidence"] is not None and r["group_confidence"] < threshold
        ]
        sweep.append(
            {
                "threshold": threshold,
                "high_confidence_count": len(high),
                "high_confidence_disagreements": sum(not r["group_agrees"] for r in high),
                "low_confidence_count": len(low),
                "low_confidence_disagreements": sum(not r["group_agrees"] for r in low),
                "unknown_confidence_count": sum(r["group_confidence"] is None for r in known),
            }
        )
    metadata_path = raw.with_suffix(".meta.json")
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    return {
        "saved_run_metadata": {
            "model": metadata.get("model"),
            "started": metadata.get("started"),
            "location_context_used": metadata.get("args", {}).get("no_place_names") == "False",
            "uncommitted_source_at_run": metadata.get("git", {}).get(
                "uncommitted_changes_in_prompts_or_backend"
            ),
        },
        "sample_n": len(rows),
        "prediction_errors": errors,
        "reference_type": "iNaturalist community labels, not independent expert adjudication",
        "known_reference_n": len(known),
        "pooled_group_agreement_count": sum(r["group_agrees"] for r in known),
        "missing_or_tied_prediction_n": sum(r["predicted_group"] is None for r in known),
        "per_group": per_group,
        "confidence_sweep": sweep,
        "source_sha256": {"manifest": sha(manifest), "predictions": sha(raw)},
        "disagreements": [
            {k: v for k, v in r.items() if k != "identity"}
            for r in results
            if not r["group_agrees"]
        ],
    }


def condition_analysis(root, candidates_path):
    run = json.loads((root / "run.json").read_text())
    if run["fingerprint"]["mode"] != "live":
        raise ValueError("Scripted baseline outputs cannot validate real-photo predictions")
    candidates = [
        json.loads(line) for line in candidates_path.read_text().splitlines() if line.strip()
    ]
    if sha(candidates_path) != run["fingerprint"]["manifest_sha256"]:
        raise ValueError("Condition manifest fingerprint mismatch")
    predictions = [
        json.loads(p.read_text()) for p in sorted((root / "predictions").glob("*.json"))
    ]
    candidate_ids = {r["case_id"] for r in candidates}
    if len(predictions) != len({r["case_id"] for r in predictions}):
        raise ValueError("Repeated current condition predictions")
    if any(
        r.get("mode") != "live"
        or r.get("run_id") != run["run_id"]
        or r["case_id"] not in candidate_ids
        for r in predictions
    ):
        raise ValueError("Prediction provenance mismatch")
    candidate_map = {row["case_id"]: row for row in candidates}
    for prediction in predictions:
        expected = (candidate_map[prediction["case_id"]].get("photo") or {}).get("sha256")
        if not expected or prediction.get("photo_sha256") != expected:
            raise ValueError("Prediction photo fingerprint mismatch")
    assessed = []
    confidence_audit = Counter()
    statuses = Counter()
    for row in predictions:
        statuses[row.get("status", "unknown")] += 1
        analysis = row.get("analysis") or {}
        assessment = analysis.get("assessment")
        identity = analysis.get("identification")
        if not isinstance(assessment, dict) or not isinstance(identity, dict):
            continue
        # Older parsed outputs may contain default confidence values. Replay only
        # the raw model-provided condition confidence, never a parser default.
        assessment = json.loads(json.dumps(assessment))
        raw_assessment = (analysis.get("raw_responses") or {}).get("assessment")
        injury = assessment.get("injury") or {}
        if isinstance(raw_assessment, dict):
            reported = score(raw_assessment.get("injury_confidence"))
            if score(injury.get("confidence")) != reported:
                confidence_audit["stored_vs_raw_mismatch"] += 1
            if reported is None:
                confidence_audit["missing_or_invalid_raw_condition_score"] += 1
            assessment["injury"] = {**injury, "confidence": reported}
        else:
            confidence_audit["raw_condition_response_unavailable"] += 1
            assessment["injury"] = {**injury, "confidence": None}
        # Replay eligibility is constructed. These are not dispatch cases.
        assessed.append(
            SimpleNamespace(
                status="awaiting_dispatch",
                duplicate_of=None,
                identification_json=identity,
                assessment_json=assessment,
                latitude=None,
                longitude=None,
                severity_level=assessment.get("severity_level"),
                entanglement_present=(assessment.get("injury") or {}).get(
                    "entanglement", False
                ),
            )
        )
    sweep = []
    for threshold in THRESHOLDS:
        suggestions = [suggest(row, threshold) for row in assessed]
        signals = Counter(
            signal["code"]
            for suggestion in suggestions
            if suggestion
            for signal in suggestion["signals"]
        )
        sweep.append(
            {
                "threshold": threshold,
                "assessed_n": len(assessed),
                "suggestion_count": sum(s is not None for s in suggestions),
                "urgent_parallel_count": sum(
                    bool(s and s["urgent_parallel_review"]) for s in suggestions
                ),
                "signal_counts": dict(signals),
            }
        )
    reviews = list((root / "reviews").glob("*.json")) if (root / "reviews").exists() else []
    return {
        "sample_n": len(candidates),
        "current_predictions_n": len(predictions),
        "assessed_n": len(assessed),
        "condition_confidence_audit": dict(confidence_audit),
        "status_counts": dict(statuses),
        "saved_review_file_count": len(reviews),
        "expert_labels_available_in_run_metadata": run.get("expert_labels_available"),
        "model": run["fingerprint"]["model"],
        "run_id": run["run_id"],
        "model_run_created_at": run["created_at"],
        "manifest_sha256": sha(candidates_path),
        "run_sha256": sha(root / "run.json"),
        "prediction_files_sha256": {
            p.name: sha(p) for p in sorted((root / "predictions").glob("*.json"))
        },
        "policy_replay_sweep": sweep,
        "clinical_accuracy": None,
        "verification_request_precision": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("var/real-drone-validation.json"))
    args = parser.parse_args()
    report = {
        "analysis_type": "retrospective_development_data",
        "threshold_is_validated": False,
        "configuration_changed": False,
        "policy_source_sha256": sha(Path("backend/lifejacket/services/drone_suggestions.py")),
        "identification": identification_analysis(
            Path("research/identification_eval/manifest.csv"),
            Path("research/identification_eval/results/first_look_20261005_172608.jsonl"),
        ),
        "condition": condition_analysis(
            args.condition_run,
            Path("research/public_condition_pilot/pilot_v1/candidates.jsonl"),
        ),
        "limitations": [
            "Convenience development samples; not independent hold-out or aerial validation.",
            "Identification run includes location context; condition run uses pixels only.",
            "Animal-group agreement does not label whether a drone observation would help.",
            "No expert condition or verification-needed labels; "
            "no clinical accuracy estimate.",
            "Saved historical model outputs; current model and "
            "prompt quality are not retested.",
            "A policy suggestion is neither flight feasibility nor dispatch authorization.",
            "Condition replay uses a constructed eligible workflow state; "
            "creates no real cases.",
        ],
    }
    with Path("research/identification_eval/manifest.csv").open() as handle:
        reference_ids = {str(row["observation_id"]) for row in csv.DictReader(handle)}
    condition_ids = {
        str(json.loads(line)["observation_id"])
        for line in Path("research/public_condition_pilot/pilot_v1/candidates.jsonl")
        .read_text()
        .splitlines()
        if line.strip()
    }
    report["development_sample_overlap_observations"] = len(reference_ids & condition_ids)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
