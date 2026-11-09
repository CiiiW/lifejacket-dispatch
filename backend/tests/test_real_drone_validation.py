"""Validate retrospective-analysis safeguards, not model quality."""

import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "scripts/validate_real_drone_data.py"
spec = importlib.util.spec_from_file_location("real_drone_validation", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_species_uncertainty_is_pooled_at_routing_group():
    group, confidence = module.pooled_prediction(
        {
            "candidates": [
                {"animal_group": "pinniped", "confidence": 0.5},
                {"animal_group": "pinniped", "confidence": 0.45},
                {"animal_group": "cetacean", "confidence": 0.05},
            ]
        }
    )
    assert group == "pinniped" and confidence == 0.95


def test_tied_groups_are_not_counted_as_a_confident_choice():
    group, confidence = module.pooled_prediction(
        {
            "candidates": [
                {"animal_group": "pinniped", "confidence": 0.5},
                {"animal_group": "cetacean", "confidence": 0.5},
            ]
        }
    )
    assert group is None and confidence == 0.5


def test_scripted_baseline_is_rejected(tmp_path):
    (tmp_path / "run.json").write_text(json.dumps({"fingerprint": {"mode": "dry_run"}}))
    with pytest.raises(ValueError, match="Scripted"):
        module.condition_analysis(tmp_path, tmp_path / "absent.jsonl")


def test_changed_collection_is_rejected(tmp_path):
    (tmp_path / "run.json").write_text(
        json.dumps(
            {
                "fingerprint": {"mode": "live", "manifest_sha256": "wrong"},
            }
        )
    )
    candidates = tmp_path / "cases.jsonl"
    candidates.write_text('{"case_id":"one","photo":{"sha256":"original-photo"}}\n')
    with pytest.raises(ValueError, match="fingerprint"):
        module.condition_analysis(tmp_path, candidates)


def test_repeated_prediction_cases_cannot_inflate_agreement(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("case_id,animal_group\none,pinniped\n")
    raw = tmp_path / "saved.jsonl"
    row = json.dumps({"case_id": "one", "variant_type": "original", "response": {}})
    raw.write_text(row + "\n" + row + "\n")
    with pytest.raises(ValueError, match="Repeated"):
        module.identification_analysis(manifest, raw)


def test_old_parser_default_is_not_treated_as_model_confidence(tmp_path):
    candidates = tmp_path / "cases.jsonl"
    candidates.write_text('{"case_id":"one","photo":{"sha256":"original-photo"}}\n')
    (tmp_path / "run.json").write_text(
        json.dumps(
            {
                "run_id": "real-run",
                "created_at": "2026-10-23T00:00:00Z",
                "fingerprint": {
                    "mode": "live",
                    "model": "saved-model",
                    "manifest_sha256": module.sha(candidates),
                },
            }
        )
    )
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    (predictions / "one.json").write_text(
        json.dumps(
            {
                "case_id": "one",
                "photo_sha256": "original-photo",
                "mode": "live",
                "run_id": "real-run",
                "status": "completed",
                "analysis": {
                    "identification": {
                        "candidates": [{"animal_group": "pinniped", "confidence": 1.0}]
                    },
                    "assessment": {
                        "injury": {"confidence": 0.95},
                        "severity_level": "monitor",
                    },
                    "raw_responses": {"assessment": {}},
                },
            }
        )
    )
    result = module.condition_analysis(tmp_path, candidates)
    assert result["condition_confidence_audit"]["stored_vs_raw_mismatch"] == 1
    assert result["condition_confidence_audit"]["missing_or_invalid_raw_condition_score"] == 1
    assert result["policy_replay_sweep"][-1]["suggestion_count"] == 0


def test_prediction_from_a_different_photo_is_rejected(tmp_path):
    candidates = tmp_path / "cases.jsonl"
    candidates.write_text('{"case_id":"one","photo":{"sha256":"original-photo"}}\n')
    (tmp_path / "run.json").write_text(
        json.dumps(
            {
                "run_id": "real-run",
                "fingerprint": {"mode": "live", "manifest_sha256": module.sha(candidates)},
            }
        )
    )
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    (predictions / "one.json").write_text(
        json.dumps(
            {
                "case_id": "one",
                "mode": "live",
                "run_id": "real-run",
                "photo_sha256": "different-photo",
            }
        )
    )
    with pytest.raises(ValueError, match="photo fingerprint"):
        module.condition_analysis(tmp_path, candidates)
