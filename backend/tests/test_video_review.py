import hashlib
import json

import pytest
from lifejacket.drones.video import write_review


@pytest.fixture
def bundle(tmp_path):
    manifest = {
        "metadata": {
            "evidence_kind": "wildlife_recording",
            "source": "Public test clip",
            "rights_note": "Credit: source",
        },
        "source": {"sha256": "a" * 64},
        "sample_limit_reached": False,
        "frames": [
            {
                "path": "frames/0001.jpg",
                "sha256": "b" * 64,
                "offset_seconds": 2.5,
                "captured_at": None,
            }
        ],
    }

    def save():
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        return hashlib.sha256((tmp_path / "manifest.json").read_bytes()).hexdigest()

    fingerprint = save()
    results = {
        "manifest_sha256": fingerprint,
        "frames": [
            {
                "path": "frames/0001.jpg",
                "status": "detected",
                "animals": [
                    {
                        "box": [100, 200, 300, 400],
                        "description": "Several animals",
                        "kind": "mammal",
                    }
                ],
            }
        ],
    }
    return tmp_path, manifest, results, save


def test_box_coordinates_and_manual_sheet_preserve_evidence(bundle):
    root, manifest, results, _ = bundle
    before = json.dumps(results, sort_keys=True)
    write_review(root, manifest, results)
    page = (root / "review.html").read_text()
    assert '<rect x="200" y="100" width="200" height="200"/>' in page
    assert 'viewBox="0 0 1000 1000" preserveAspectRatio="none"' in page
    assert "Possible group / colony" in page and "Not an animal" in page
    assert "not individual animal counts" in page
    assert 'type="application/json" id="review-data"' in page
    assert 'data-region="0"' in page
    assert "independent_ground_truth: false" in (root / "review.js").read_text()
    assert json.dumps(results, sort_keys=True) == before


@pytest.mark.parametrize(
    "box",
    [
        [300, 200, 100, 400],
        [0, 0, 0, 50],
        [-1, 0, 10, 50],
        [0, 0, 1001, 50],
        [True, 0, 10, 50],
        [0, 1],
        [0, 0, float("nan"), 50],
    ],
)
def test_bad_boxes_are_visible_warnings_not_unsafe_overlays(bundle, box):
    root, manifest, results, _ = bundle
    results["frames"][0]["animals"][0]["box"] = box
    write_review(root, manifest, results)
    page = (root / "review.html").read_text()
    assert "Invalid box: overlay omitted" in page
    assert "<rect x=" not in page


def test_model_and_source_text_cannot_escape_html_or_embedded_json(bundle):
    root, manifest, results, save = bundle
    attack = '</script><img src=x onerror="alert(1)">'
    manifest["metadata"]["source"] = attack
    manifest["metadata"]["rights_note"] = attack
    results["manifest_sha256"] = save()
    results["frames"][0]["animals"][0]["description"] = attack
    write_review(root, manifest, results)
    page = (root / "review.html").read_text()
    assert attack not in page
    assert "&lt;/script&gt;" in page
    assert r"\u003c/script\u003e" in page


def test_stale_prediction_or_manifest_rejected(bundle):
    root, manifest, results, _ = bundle
    results["manifest_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="different manifest"):
        write_review(root, manifest, results)
    manifest["metadata"]["source"] = "Changed"
    with pytest.raises(ValueError, match="saved evidence"):
        write_review(root, manifest)


def test_review_storage_scope_changes_with_predictions(bundle):
    root, manifest, results, _ = bundle
    write_review(root, manifest, results)
    before = (root / "review.html").read_text()
    results["frames"][0]["animals"] = []
    write_review(root, manifest, results)
    after = (root / "review.html").read_text()

    def data(page):
        return json.loads(page.split('id="review-data">')[1].split("</script>")[0])

    assert data(before)["manifest_sha256"] == data(after)["manifest_sha256"]
    assert data(before)["predictions_sha256"] != data(after)["predictions_sha256"]


def test_duplicate_prediction_frames_rejected(bundle):
    root, manifest, results, _ = bundle
    results["frames"].append(results["frames"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        write_review(root, manifest, results)
