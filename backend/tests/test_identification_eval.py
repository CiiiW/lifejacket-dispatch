"""Multi-animal images cannot be scored without an explicit target label."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from lifejacket.chatbot.session import StepAction


def _runner():
    path = Path(__file__).parents[2] / "research/identification_eval/run_first_look.py"
    spec = importlib.util.spec_from_file_location("identification_first_look", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multi_animal_image_without_label_is_excluded_from_accuracy(tmp_path):
    runner = _runner()
    chat = SimpleNamespace(
        state=SimpleNamespace(
            identification=None, detections=[object(), object()],
            selected_detection=None, detection_status="found",
            identification_stop_reason=None,
        ),
        last_turn=SimpleNamespace(action=StepAction.ASK_WHICH_ANIMAL, reason="choose"),
        pipeline=SimpleNamespace(
            identification_agent=SimpleNamespace(last_metrics={})
        ),
    )
    row = runner.score(chat, {})
    assert row["error"] == "selection_required"
    assert row["detected_count"] == 2

    targets_file = tmp_path / "targets.csv"
    targets_file.write_text(
        "case_id,variant_type,level,animal_number\ncase1,original,0,2\n",
        encoding="utf-8",
    )
    assert runner.load_targets(targets_file) == {("case1", "original", 0): 2}
