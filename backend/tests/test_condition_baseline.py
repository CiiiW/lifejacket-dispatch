"""Research results stay provisional, image-only, resumable and target-specific."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from lifejacket.llm.client import LLMCallError
from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.research.condition_baseline import BaselineStore, Conflict, HumanReview, Target
from lifejacket.research.review_app import create_app
from PIL import Image
from pydantic import ValidationError


@pytest.fixture
def collection(tmp_path):
    root = tmp_path / "photoset"
    (root / "photos").mkdir(parents=True)
    path = root / "photos/a.jpg"
    Image.new("RGB", (400, 200), "red").save(path)
    row = {
        "case_id": "inat_1_2",
        "taxon": {"scientific_name": "SECRET_SPECIES"},
        "community_evidence": [{"text": "SECRET_WOUND_REPORT"}],
        "photo": {
            "file": "photos/a.jpg",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }
    (root / "candidates.jsonl").write_text(json.dumps(row) + "\n")
    return root


def client(boxes=1):
    c = ScriptedLLMClient.scenario("sea_lion")
    c.queue("detection", {"animals": [{"box": [100, 100, 800, 800]} for _ in range(boxes)]})
    return c


def store(collection, tmp_path, c=None, **kwargs):
    return BaselineStore(
        collection, tmp_path / "run", client_factory=lambda: c or client(), **kwargs
    )


def review(prediction=None, **changes):
    data = {
        "expected_revision": 0,
        "expected_prediction_id": prediction,
        "reviewer": "Volunteer",
        "qualification": "Not an expert",
        "animal_present": "yes",
        "animal_group": "pinniped",
        "target_box": [100, 100, 800, 800],
        "viewpoint": "ground",
        "quality": "limited",
    }
    return HumanReview(**(data | changes))


def test_image_only_and_resume(collection, tmp_path):
    c = client()
    s = store(collection, tmp_path, c)
    p = s.analyze("inat_1_2")
    assert p["status"] == "completed"
    assert p["analysis"]["assessment"]["requires_human_review"] is True
    assert len(c.calls) == 3
    assert all(call.image_count == 1 for call in c.calls)
    assert all(
        "SECRET_SPECIES" not in call.prompt and "SECRET_WOUND_REPORT" not in call.prompt
        for call in c.calls
    )
    assert s.analyze("inat_1_2", resume=True) == p
    assert len(c.calls) == 3
    assert s.summary()["accuracy"] is None


@pytest.mark.parametrize("boxes,status", [(0, "no_detection"), (2, "selection_required")])
def test_detection_selection_and_manual_misses(collection, tmp_path, boxes, status):
    c = client(boxes)
    s = store(collection, tmp_path, c)
    p = s.analyze("inat_1_2")
    assert p["status"] == status
    assert len(c.calls) == 1
    t = Target(expected_prediction_id=p["prediction_id"], manual_box=[200, 200, 700, 700])
    selected = s.analyze("inat_1_2", t)
    assert selected["status"] == "completed"
    assert selected["target_basis"] == "manual_box"
    assert len(list((s.run_dir / "attempts/inat_1_2").glob("*.json"))) == 2
    with pytest.raises(Conflict):
        s.analyze("inat_1_2", t)


def test_detected_animal_selection(collection, tmp_path):
    s = store(collection, tmp_path, client(2))
    p = s.analyze("inat_1_2")
    result = s.analyze(
        "inat_1_2", Target(expected_prediction_id=p["prediction_id"], animal_number=2)
    )
    assert result["animal_number"] == 2
    assert result["status"] == "completed"


def test_failure_is_persisted_and_retried(collection, tmp_path):
    c = client()
    c.script["detection"].insert(0, LLMCallError("unavailable", attempts=3))
    s = store(collection, tmp_path, c)
    p = s.analyze("inat_1_2")
    assert p["status"] == "failed" and p["error"]["attempts"] == 3
    assert s.analyze("inat_1_2", resume=True)["status"] == "completed"


def test_integrity_and_fingerprint(collection, tmp_path):
    s = store(collection, tmp_path)
    (collection / "photos/a.jpg").write_bytes(b"changed")
    assert s.analyze("inat_1_2")["status"] == "failed"
    with pytest.raises(ValueError, match="snapshot"):
        s.save_review("inat_1_2", review())
    with pytest.raises(Conflict, match="changed"):
        store(collection, tmp_path, scripted=True)


def test_review_history_conflict_and_provisional_comparison(collection, tmp_path):
    s = store(collection, tmp_path)
    p = s.analyze("inat_1_2")
    body = review(p["prediction_id"], abnormal_posture="observed")
    r = s.save_review("inat_1_2", body)
    assert r["expert_reviewed"] is False
    with pytest.raises(Conflict):
        s.save_review("inat_1_2", body)
    counts = s.summary()["provisional_condition_comparison"]["pinniped"]
    assert counts["abnormal_posture"]["tp"] == 1
    assert counts["bleeding"]["comparable"] == 0
    assert counts["bleeding"]["not_assessable"] == 1
    s.save_review("inat_1_2", review(p["prediction_id"], expected_revision=1))
    assert len(list((s.run_dir / "review_history/inat_1_2").glob("*.json"))) == 2
    s.analyze("inat_1_2")
    assert s.summary()["provisional_condition_comparison"] == {}


def test_review_validates_target_and_never_fills_negatives():
    with pytest.raises(ValidationError):
        review(target_box=None)
    with pytest.raises(ValidationError):
        review(animal_present="no")
    with pytest.raises(ValidationError):
        Target(manual_box=[200, 100, 100, 500])
    with pytest.raises(ValidationError):
        Target(manual_box=[0, 0, 100, 100], animal_number=1)
    assert review().bleeding == "uncertain"


def test_private_api_has_no_dispatch_routes(collection, tmp_path):
    s = store(collection, tmp_path, scripted=True)
    api = TestClient(create_app(s))
    assert api.get("/").status_code == 200
    assert api.get("/api/cases/inat_1_2/photo").status_code == 200
    assert api.get("/api/cases/inat_99_99").status_code == 404
    assert api.post("/api/cases/inat_1_2/rerun", json={}).json()["status"] == "completed"
    assert api.post("/api/cases/inat_1_2/rerun", json={}).status_code == 409
    assert api.get("/api/export").json()["summary"]["accuracy"] is None
    assert api.get("/api/incidents").status_code == 404
    assert api.get("/api/summary").json()["expert_reviewed_count"] == 0
