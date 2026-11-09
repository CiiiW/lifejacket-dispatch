"""Evaluation must reject leakage and absent reviewer labels."""

import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "scripts/evaluate_drone_thresholds.py"
spec = importlib.util.spec_from_file_location("threshold_evaluation", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def dataset():
    return {
        "dataset_kind": "reviewed",
        "cases": [
            {
                "case_id": "one",
                "animal_event_id": "animal",
                "split": "validation",
                "verification_needed": True,
                "label_provenance": "reviewer-01",
                "incident": {
                    "identification_json": {
                        "resolution": {
                            "rank": "group",
                            "animal_group": "pinniped",
                            "confidence": 0.8,
                        }
                    }
                },
            },
        ],
    }


def test_real_policy_threshold_boundary_and_unvalidated_output():
    result = module.evaluate(dataset(), (0.8, 0.9))
    assert result["metrics"][0]["fn"] == 1
    assert result["metrics"][1]["tp"] == 1
    assert result["threshold_is_validated"] is False
    assert result["configuration_changed"] is False


@pytest.mark.parametrize(
    "mutation", ["missing_label", "missing_provenance", "cross_split", "duplicate_id"]
)
def test_invalid_evaluation_data_rejected(mutation):
    data = dataset()
    if mutation == "missing_label":
        del data["cases"][0]["verification_needed"]
    elif mutation == "missing_provenance":
        del data["cases"][0]["label_provenance"]
    else:
        second = {**data["cases"][0]}
        if mutation == "cross_split":
            second.update(case_id="two", split="test")
        data["cases"].append(second)
    with pytest.raises(ValueError):
        module.evaluate(data)


def test_holdout_is_not_swept_for_threshold_selection():
    data = dataset()
    data["cases"].append(
        {
            **data["cases"][0],
            "case_id": "holdout",
            "animal_event_id": "other-animal",
            "split": "test",
        }
    )
    exploratory = module.evaluate(data, (0.6, 0.9))
    assert all(m["split"] == "validation" for m in exploratory["metrics"])
    assert exploratory["held_out_test_evaluated"] is False
    locked = module.evaluate(data, (0.6, 0.9), test_threshold=0.85)
    held_out = [m for m in locked["metrics"] if m["split"] == "test"]
    assert len(held_out) == 1
    assert held_out[0]["threshold"] == 0.85
    assert locked["threshold_is_validated"] is False
