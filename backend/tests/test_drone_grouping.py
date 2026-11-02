import copy

import pytest
from lifejacket.drones.grouping import suggest_groups


def animal(box=None, kind="seal"):
    return {"box": box or [100, 100, 300, 300], "kind": kind, "description": "Scripted"}


def frame(time, animals=None, **changes):
    row = {
        "demo_id": f"demo_{time}",
        "revision": 0,
        "status": "pending",
        "metadata": {
            "evidence_kind": "synthetic_test",
            "source": "Scripted rectangles, not animals",
            "rights_note": "Generated",
            "source_sha256": "a" * 64,
            "frame_sha256": "b" * 64,
            "offset_seconds": time,
            "detection_status": "completed",
            "detection": {"animals": [animal()] if animals is None else animals},
        },
    }
    row.update(changes)
    return row


def lengths(result):
    return [len(group["members"]) for group in result["groups"]]


def test_overlap_groups_moving_boxes_and_keeps_candidate_references():
    frames = [frame(2, [animal([100, 120, 300, 320])]), frame(0), frame(1)]
    before = copy.deepcopy(frames)
    result = suggest_groups(frames)
    assert lengths(result) == [3]
    assert [m["demo_id"] for m in result["groups"][0]["members"]] == [
        "demo_0",
        "demo_1",
        "demo_2",
    ]
    assert result["persisted"] is False
    assert frames == before


def test_two_targets_never_collapse_to_one():
    boxes = [animal(), animal([600, 600, 800, 800])]
    assert lengths(suggest_groups([frame(t, boxes) for t in range(4)])) == [4, 4]


@pytest.mark.parametrize("state", ["failed", "not_run", "empty"])
def test_short_missed_frame_preserves_association_and_reports_failure(state):
    middle = frame(1, [])
    if state != "empty":
        middle["metadata"].update(detection_status=state, detection=None)
    result = suggest_groups([frame(0), middle, frame(2)])
    assert lengths(result) == [2]
    assert len(result["warnings"]) == (0 if state == "empty" else 1)


def test_long_gap_reentry_kind_change_and_camera_jump_start_new_groups():
    assert lengths(suggest_groups([frame(0), frame(4)])) == [1, 1]
    assert lengths(suggest_groups([frame(0), frame(1, [animal(kind="bird")])])) == [1, 1]
    assert lengths(suggest_groups([frame(0), frame(1, [animal([600, 600, 800, 800])])])) == [
        1,
        1,
    ]


def test_many_to_one_is_ambiguous_and_does_not_merge_history():
    result = suggest_groups([frame(0, [animal(), animal()]), frame(1), frame(2)])
    assert lengths(result) == [1, 1, 2]
    assert result["groups"][-1]["association"] == "ambiguous"


def test_one_to_many_is_ambiguous_and_tracks_remain_separate():
    result = suggest_groups([frame(0), frame(1, [animal(), animal()]), frame(2)])
    assert lengths(result) == [1, 1, 1, 1]
    assert all(g["association"] == "ambiguous" for g in result["groups"][1:])


def test_empty_frames_invalid_boxes_and_rejected_frames():
    result = suggest_groups(
        [frame(0, []), frame(1, [animal([300, 100, 100, 300])]), frame(2, status="rejected")]
    )
    assert result["groups"] == []
    assert result["excluded_rejected_frames"] == 1
    assert result["warnings"][0]["reason"] == "invalid_box"


@pytest.mark.parametrize("change", ["source", "kind", "time", "wildlife"])
def test_mixed_sources_duplicate_times_and_non_demo_evidence_rejected(change):
    first, second = frame(0), frame(1)
    if change == "source":
        second["metadata"]["source_sha256"] = "c" * 64
    elif change == "kind":
        second["metadata"]["evidence_kind"] = "toy_demo"
    elif change == "time":
        second["metadata"]["offset_seconds"] = 0
    else:
        second["metadata"]["evidence_kind"] = "wildlife_recording"
    with pytest.raises(ValueError):
        suggest_groups([first, second])


@pytest.mark.parametrize("frames", [[], [frame(i) for i in range(61)]])
def test_bounds(frames):
    with pytest.raises(ValueError):
        suggest_groups(frames)
