"""Frame selection: deterministic rules and an offline end-to-end run (no credentials)."""

import json
import shutil
import subprocess

import pytest
from lifejacket.drones.frame_select import (
    Candidate,
    ScanConfig,
    SelectConfig,
    choose_candidates,
    select_frames,
    select_from_video,
)
from lifejacket.drones.video import VideoMetadata
from lifejacket.llm.client import LLMCallError
from lifejacket.llm.fake import ScriptedLLMClient


def row(t, *, view="full_body", side="left", clarity=4, size=3, shot=0, sharp=100.0,
        notable="", clear=False, visible=True):
    return {
        "path": f"candidates/{int(t * 10):04d}.jpg",
        "candidate": {"offset_seconds": t, "sharpness": sharp, "brightness": 120.0, "shot": shot},
        "observation": {
            "animal_visible": visible, "view": view, "side": side, "clarity": clarity,
            "animal_size": size, "environment": "beach", "notable": notable,
            "notable_clear": clear,
        },
    }


def test_selects_different_views_and_sides_up_to_the_limit():
    rows = [
        row(1, view="wide_context", side="unknown"),
        row(10, view="full_body", side="left"),
        row(20, view="full_body", side="right"),
        row(30, view="head_face", side="front"),
        row(40, view="body_detail", side="unknown"),
        row(50, view="full_body", side="left"),  # repeat of t=10
    ]
    chosen = select_frames(rows, SelectConfig(max_frames=5))
    assert len(chosen) <= 5
    assert {r["observation"]["view"] for r in chosen} >= {"full_body", "head_face", "wide_context"}
    assert [r["candidate"]["offset_seconds"] for r in chosen] == sorted(
        r["candidate"]["offset_seconds"] for r in chosen
    )
    assert all(r["selected_reason"] for r in chosen)


def test_returns_fewer_frames_instead_of_padding_with_repeats():
    rows = [row(t, view="full_body", side="left") for t in (1, 10, 20, 30, 40)]
    assert len(select_frames(rows, SelectConfig(max_frames=5))) == 1


def test_clear_notable_detail_is_always_included():
    rows = [row(t, view="full_body", side="left", clarity=5, size=5) for t in (1, 10, 20)]
    rows.append(
        row(30, view="body_detail", side="unknown", clarity=3, size=2,
            notable="possible line wrapped around flipper", clear=True)
    )
    chosen = select_frames(rows, SelectConfig(max_frames=2))
    assert any(r["observation"]["notable"] for r in chosen)


def test_unclear_notable_does_not_force_inclusion_or_bonus():
    plain = row(1, view="full_body", side="left", clarity=5, size=5)
    vague = row(10, view="full_body", side="left", clarity=3, size=2,
                notable="maybe something", clear=False)
    chosen = select_frames([plain, vague], SelectConfig(max_frames=2))
    assert [r["candidate"]["offset_seconds"] for r in chosen] == [1]


def test_ignores_frames_without_a_visible_animal_or_with_poor_clarity():
    rows = [row(1, visible=False), row(5, clarity=1), row(9, clarity=4)]
    chosen = select_frames(rows)
    assert [r["candidate"]["offset_seconds"] for r in chosen] == [9]
    assert select_frames([row(1, visible=False)]) == []


def test_failed_observations_are_skipped():
    failed = {"path": "x", "candidate": {"offset_seconds": 1, "sharpness": 1, "shot": 0},
              "observation": None}
    assert select_frames([failed, row(5)])[0]["candidate"]["offset_seconds"] == 5


def cand(t, sharp=100.0, brightness=120.0, shot=0, hash_=0):
    return Candidate(offset_seconds=t, sharpness=sharp, brightness=brightness, shot=shot,
                     hash=hash_)


def test_scan_filter_drops_blurred_dark_and_duplicate_frames():
    frames = [
        cand(0, hash_=0b0),
        cand(0.5, hash_=0b0),  # duplicate of previous kept frame
        cand(1, sharp=5, hash_=(1 << 40) - 1),  # blurred
        cand(1.5, brightness=2, hash_=(1 << 30) - 1),  # too dark
        cand(2, hash_=(1 << 20) - 1),  # genuinely different
    ]
    kept = choose_candidates(frames, ScanConfig())
    assert [c.offset_seconds for c in kept] == [0, 2]


def test_still_scene_is_still_sampled_over_time():
    frames = [cand(t * 0.5, hash_=0) for t in range(0, 61)]  # identical for 30 s
    kept = choose_candidates(frames, ScanConfig(max_gap_seconds=8))
    assert [c.offset_seconds for c in kept] == [0, 8, 16, 24]


def test_candidate_cap_keeps_the_whole_timeline_covered():
    frames = [cand(t, hash_=(1 << (t % 60)) * 7919) for t in range(0, 300)]
    kept = choose_candidates(frames, ScanConfig(max_candidates=10, dedupe_distance=1))
    assert len(kept) <= 10
    assert max(c.offset_seconds for c in kept) > 200


pytestmark_ffmpeg = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg not installed"
)


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "input.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=320x180:rate=10", "-t", "20", "-c:v", "mpeg4", "-threads", "1",
         str(path)],
        check=True,
    )
    return path


METADATA = VideoMetadata(evidence_kind="synthetic_test", source="ffmpeg testsrc2",
                         rights_note="generated for tests")


def _reply(view, side, *, notable="", clear=False, clarity=4):
    return {"animal_visible": True, "view": view, "side": side, "clarity": clarity,
            "animal_size": 3, "environment": "beach", "notable": notable,
            "notable_clear": clear}


@pytestmark_ffmpeg
def test_end_to_end_with_scripted_model(clip, tmp_path):
    client = ScriptedLLMClient()
    client.queue(
        "frame_observation",
        _reply("wide_context", "unknown"),
        _reply("full_body", "left"),
        _reply("head_face", "front"),
        _reply("body_detail", "unknown", notable="possible wound", clear=True),
    )
    out = tmp_path / "bundle"
    manifest = select_from_video(
        clip, out, METADATA, client=client, scan=ScanConfig(scan_fps=2, max_candidates=8, max_gap_seconds=2),
        workers=1,
    )
    chosen = manifest["selection"]["selected"]
    assert 1 <= len(chosen) <= 5
    assert any(item["notable"] == "possible wound" for item in chosen)
    for item in chosen:
        assert (out / item["path"]).is_file()
    saved = json.loads((out / "selection.json").read_text())
    assert saved["source"]["sha256"] == manifest["source"]["sha256"]
    assert saved["limitations"]
    assert (out / "review.html").is_file()
    assert not list(tmp_path.glob(".select-*"))


@pytestmark_ffmpeg
def test_refuses_to_overwrite_existing_output(clip, tmp_path):
    (tmp_path / "bundle").mkdir()
    with pytest.raises(ValueError, match="already exists"):
        select_from_video(clip, tmp_path / "bundle", METADATA, client=ScriptedLLMClient())


@pytestmark_ffmpeg
def test_all_model_failures_publish_nothing(clip, tmp_path):
    client = ScriptedLLMClient()
    client.queue("frame_observation", LLMCallError("down", attempts=1))
    with pytest.raises(ValueError, match="Every model observation failed"):
        select_from_video(
            clip, tmp_path / "bundle", METADATA, client=client,
            scan=ScanConfig(max_candidates=4, max_gap_seconds=2), workers=1,
        )
    assert not (tmp_path / "bundle").exists()
    assert not list(tmp_path.glob(".select-*"))


@pytestmark_ffmpeg
def test_rejects_non_video_files(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not a video")
    with pytest.raises(ValueError, match="MP4, MOV or MKV"):
        select_from_video(bad, tmp_path / "bundle", METADATA, client=ScriptedLLMClient())
