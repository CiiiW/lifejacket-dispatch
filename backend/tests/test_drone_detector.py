"""The aerial detector's pure parts, its fake, and its refusal to load junk.

No network, no onnxruntime, no model file. Everything here runs on a bare
`pip install -r backend/requirements.txt`, which is the point: the optional
extra must stay optional.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from lifejacket.drones.detector import (
    CLASS_NAMES,
    Detection,
    DetectorError,
    DetectorSource,
    FakeDetector,
    Letterbox,
    decode,
    decode_detr,
    file_sha256,
    load_detector,
    nms,
)

# --- letterbox ------------------------------------------------------------


def test_letterbox_fits_the_long_side_and_centres_the_short_one():
    box = Letterbox.fit((1920, 1080), 960)
    assert box.scale == pytest.approx(0.5)
    assert box.pad_x == pytest.approx(0.0)
    assert box.pad_y == pytest.approx((960 - 540) / 2)


def test_letterbox_round_trips_a_point_back_to_source_pixels():
    box = Letterbox.fit((1920, 1080), 960)
    # A point at the centre of the source maps to the centre of the canvas.
    x, y = box.to_source(480.0, 480.0)
    assert (x, y) == pytest.approx((960.0, 540.0))


def test_letterbox_rejects_a_zero_dimension():
    with pytest.raises(DetectorError, match="zero dimension"):
        Letterbox.fit((0, 100), 640)


# --- nms ------------------------------------------------------------------


def test_nms_suppresses_a_duplicate_and_keeps_a_distinct_box():
    boxes = [[0, 0, 10, 10], [1, 1, 11, 11], [100, 100, 110, 110]]
    scores = [0.9, 0.8, 0.7]
    assert nms(boxes, scores, 0.45) == [0, 2]


def test_nms_keeps_both_when_the_overlap_is_below_the_threshold():
    boxes = [[0, 0, 10, 10], [9, 0, 19, 10]]
    assert nms(boxes, [0.9, 0.8], 0.45) == [0, 1]


def test_nms_on_nothing_is_empty_not_an_error():
    assert nms([], [], 0.5) == []


# --- decode ---------------------------------------------------------------


def _raw(rows: list[list[float]]) -> np.ndarray:
    """Build a (1, 4 + classes, anchors) tensor the way Ultralytics exports it."""
    return np.asarray(rows, dtype=np.float32).T[None, ...]


def test_decode_maps_a_box_back_into_original_image_coordinates():
    box = Letterbox.fit((1920, 1080), 960)
    # cx, cy, w, h in model-input pixels, then one score per class.
    raw = _raw([[480.0, 480.0, 100.0, 50.0, 0.0, 0.93, 0.0]])
    found = decode(raw, box, (1920, 1080), confidence=0.25)
    assert len(found) == 1
    assert found[0].label == "animal"
    assert found[0].confidence == pytest.approx(0.93, abs=1e-4)
    # scale 0.5, so a 100x50 input box is 200x100 in the source.
    assert found[0].box == (860, 490, 1060, 590)
    assert (found[0].width, found[0].height) == (200, 100)


def test_decode_drops_everything_below_the_confidence_floor():
    box = Letterbox.fit((640, 640), 640)
    raw = _raw([[100.0, 100.0, 20.0, 20.0, 0.1, 0.05, 0.2]])
    assert decode(raw, box, (640, 640), confidence=0.25) == []


def test_decode_picks_the_highest_scoring_class_per_anchor():
    box = Letterbox.fit((640, 640), 640)
    raw = _raw([[100.0, 100.0, 20.0, 20.0, 0.3, 0.1, 0.8]])
    found = decode(raw, box, (640, 640), confidence=0.25)
    assert [d.label for d in found] == ["vehicle"]


def test_decode_suppresses_within_a_class_but_not_across_classes():
    box = Letterbox.fit((640, 640), 640)
    raw = _raw(
        [
            [100.0, 100.0, 40.0, 40.0, 0.0, 0.9, 0.0],   # animal
            [102.0, 102.0, 40.0, 40.0, 0.0, 0.7, 0.0],   # same animal again
            [100.0, 100.0, 40.0, 40.0, 0.9, 0.0, 0.0],   # a person in that spot
        ]
    )
    found = decode(raw, box, (640, 640), confidence=0.25, iou=0.45)
    assert sorted(d.label for d in found) == ["animal", "person"]


def test_decode_clips_a_box_that_runs_off_the_edge():
    box = Letterbox.fit((640, 640), 640)
    raw = _raw([[10.0, 10.0, 60.0, 60.0, 0.0, 0.9, 0.0]])
    found = decode(raw, box, (640, 640), confidence=0.25)
    assert found[0].box[0] == 0
    assert found[0].box[1] == 0


def test_decode_accepts_the_transposed_export_shape():
    box = Letterbox.fit((640, 640), 640)
    rows = [[100.0, 100.0, 20.0, 20.0, 0.0, 0.9, 0.0]]
    straight = decode(_raw(rows), box, (640, 640))
    transposed = decode(
        np.asarray(rows, dtype=np.float32)[None, ...], box, (640, 640)
    )
    assert straight == transposed


def test_decode_refuses_a_tensor_whose_class_count_disagrees():
    box = Letterbox.fit((640, 640), 640)
    # Ten classes, but CLASS_NAMES has three. Silently relabelling would be worse.
    raw = np.zeros((1, 14, 20), dtype=np.float32)
    with pytest.raises(DetectorError, match="class count"):
        decode(raw, box, (640, 640))


def test_decode_returns_results_sorted_by_confidence():
    box = Letterbox.fit((640, 640), 640)
    raw = _raw(
        [
            [100.0, 100.0, 20.0, 20.0, 0.4, 0.0, 0.0],
            [300.0, 300.0, 20.0, 20.0, 0.0, 0.95, 0.0],
            [500.0, 500.0, 20.0, 20.0, 0.0, 0.0, 0.7],
        ]
    )
    found = decode(raw, box, (640, 640), confidence=0.25)
    assert [d.confidence for d in found] == sorted(
        (d.confidence for d in found), reverse=True
    )


# --- the fake -------------------------------------------------------------


def test_fake_returns_queued_results_in_order_then_empty():
    first = [Detection("animal", 0.91, (10, 10, 60, 48))]
    detector = FakeDetector().queue(first).queue([])
    assert detector.detect(Path("a.jpg")) == first
    assert detector.detect(Path("b.jpg")) == []
    assert detector.detect(Path("c.jpg")) == []


def test_fake_records_every_frame_it_was_asked_about():
    detector = FakeDetector()
    detector.detect(Path("one.jpg"))
    detector.detect(Path("two.jpg"))
    assert detector.calls == [Path("one.jpg"), Path("two.jpg")]


# --- weights are pinned ---------------------------------------------------


def test_source_rejects_a_branch_name_as_a_revision():
    with pytest.raises(DetectorError, match="moving target"):
        DetectorSource(repo="org/model", revision="main").validate()


def test_source_requires_a_revision_at_all():
    with pytest.raises(DetectorError, match="no revision pinned"):
        DetectorSource(repo="org/model", revision="").validate()


def test_source_requires_a_repo():
    with pytest.raises(DetectorError, match="no Hugging Face repo"):
        DetectorSource(repo="", revision="a" * 40).validate()


def test_a_full_length_commit_sha_validates():
    DetectorSource(repo="org/model", revision="a" * 40).validate()


def test_file_sha256_matches_hashlib(tmp_path: Path):
    path = tmp_path / "weights.onnx"
    path.write_bytes(b"not really a model")
    assert file_sha256(path) == hashlib.sha256(b"not really a model").hexdigest()


# --- the default is off ---------------------------------------------------


class _Settings:
    drone_detector_enabled = False


def test_load_detector_returns_the_fake_when_the_flag_is_off():
    assert isinstance(load_detector(_Settings()), FakeDetector)


def test_load_detector_defaults_to_the_fake_on_real_settings():
    # No DRONE_DETECTOR_* set, so this must not try to reach the network.
    assert isinstance(load_detector(), FakeDetector)


def test_class_names_match_dronemegadetector():
    # Read out of the published checkpoint's own model_config, not its README.
    # research/aerial_detector/dmd.py:describe_checkpoint reproduces this.
    assert CLASS_NAMES == ("person", "animal", "vehicle")


# --- DETR decoding (RF-DETR / DroneMegaDetector) --------------------------
#
# Set prediction: no NMS, normalised cxcywh, per-class sigmoid.


def _logits(rows: list[list[float]]) -> np.ndarray:
    return np.asarray(rows, dtype=np.float32)


def test_detr_denormalises_a_box_against_the_source_size():
    boxes = _logits([[0.5, 0.5, 0.25, 0.5]])          # centred, quarter wide
    found = decode_detr(boxes, _logits([[0.0, 5.0, 0.0]]), (1920, 1080), confidence=0.25)
    assert len(found) == 1
    assert found[0].label == "animal"
    assert found[0].box == (720, 270, 1200, 810)


def test_detr_applies_sigmoid_unless_told_otherwise():
    boxes = _logits([[0.5, 0.5, 0.2, 0.2]])
    # logit 0 -> sigmoid 0.5, which clears a 0.25 floor
    assert len(decode_detr(boxes, _logits([[0.0, 0.0, 0.0]]), (640, 640), confidence=0.25)) == 1
    # the same values read as probabilities are 0.0 and must not clear it
    assert (
        decode_detr(
            boxes, _logits([[0.0, 0.0, 0.0]]), (640, 640), confidence=0.25, already_sigmoid=True
        )
        == []
    )


def test_detr_keeps_overlapping_queries_because_there_is_no_nms():
    # Two near-identical boxes. The anchor decoder would suppress one; a
    # set-prediction model is trusted to have done that itself.
    boxes = _logits([[0.5, 0.5, 0.2, 0.2], [0.51, 0.51, 0.2, 0.2]])
    found = decode_detr(boxes, _logits([[0.0, 5.0, 0.0], [0.0, 4.0, 0.0]]), (640, 640))
    assert len(found) == 2


def test_detr_clips_to_the_frame():
    boxes = _logits([[0.05, 0.05, 0.4, 0.4]])
    found = decode_detr(boxes, _logits([[0.0, 5.0, 0.0]]), (640, 640), confidence=0.25)
    assert found[0].box[0] == 0 and found[0].box[1] == 0


def test_detr_accepts_a_transposed_logits_axis():
    boxes = _logits([[0.5, 0.5, 0.2, 0.2], [0.2, 0.2, 0.1, 0.1]])
    straight = _logits([[0.0, 5.0, 0.0], [0.0, 4.0, 0.0]])
    assert decode_detr(boxes, straight, (640, 640)) == decode_detr(boxes, straight.T, (640, 640))


def test_detr_refuses_a_class_count_that_disagrees():
    boxes = _logits([[0.5, 0.5, 0.2, 0.2]])
    with pytest.raises(DetectorError, match="class count differs"):
        decode_detr(boxes, np.zeros((1, 10), dtype=np.float32), (640, 640))


def test_detr_refuses_malformed_boxes():
    with pytest.raises(DetectorError, match=r"shape \(queries, 4\)"):
        decode_detr(np.zeros((5, 3), dtype=np.float32), np.zeros((5, 3)), (640, 640))


def test_detr_sorts_by_confidence():
    boxes = _logits([[0.2, 0.2, 0.1, 0.1], [0.7, 0.7, 0.1, 0.1]])
    found = decode_detr(boxes, _logits([[3.0, 0.0, 0.0], [0.0, 0.0, 6.0]]), (640, 640))
    assert [d.label for d in found] == ["vehicle", "person"]
