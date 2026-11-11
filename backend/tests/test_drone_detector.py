"""Detector handoff must preserve coordinates and distinguish absence from failure."""

import pytest
from lifejacket.models.drone_detector import DetectorFrameResult
from pydantic import ValidationError


def result(**extra):
    return DetectorFrameResult.model_validate(
        {
            "evidence_id": "a" * 32,
            "source_sha256": "b" * 64,
            "width": 640,
            "height": 360,
            "model_name": "teammate-detector",
            "model_version": "demo-v1",
            "weights_sha256": "c" * 64,
            "source_kind": "sample_footage",
            "status": "completed",
            "detections": [
                {
                    "class_name": "synthetic target",
                    "confidence": 0.8,
                    "xyxy": [64, 36, 320, 180],
                }
            ],
            **extra,
        }
    )


def test_pixel_xyxy_maps_to_existing_agent_yxyx_without_claiming_species():
    assert result().agent_detections() == [
        {"box": [100, 100, 500, 500], "description": "synthetic target", "kind": "other"}
    ]


def test_no_detection_and_model_failure_are_distinct():
    assert result(detections=[]).agent_detections() == []
    failed = result(status="failed", detections=[], error_code="model_unavailable")
    with pytest.raises(ValueError, match="Failed inference"):
        failed.agent_detections()
    with pytest.raises(ValidationError):
        result(status="failed", detections=[])
    with pytest.raises(ValidationError):
        result(error_code="inference_failed")


@pytest.mark.parametrize(
    "xyxy", [[-1, 0, 10, 20], [0, 0, 641, 20], [20, 10, 10, 30], [0, 0, 10, float("nan")]]
)
def test_bad_boxes_are_rejected(xyxy):
    with pytest.raises(ValidationError):
        result(detections=[{"class_name": "target", "confidence": 0.8, "xyxy": xyxy}])


def test_unexpected_triage_or_location_fields_are_rejected():
    with pytest.raises(ValidationError):
        result(severity="critical")
    with pytest.raises(ValidationError):
        result(latitude=1.2)
