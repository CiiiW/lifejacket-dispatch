"""Public candidate collection must not manufacture medical ground truth."""

import importlib.util
import io
from pathlib import Path

import pytest
from PIL import Image

MODULE_PATH = Path(__file__).parents[2] / "research/public_condition_pilot/collect.py"
spec = importlib.util.spec_from_file_location("public_condition_pilot", MODULE_PATH)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def observation(**changes):
    obs = {
        "id": 42,
        "license_code": "cc-by",
        "description": "No visible bleeding; possible entanglement?",
        "user": {"id": 5},
        "taxon": {"id": 9, "name": "Test species"},
        "photos": [
            {
                "id": 88,
                "license_code": "cc-by",
                "attribution": "Test creator CC BY",
                "url": "https://inaturalist-open-data.s3.amazonaws.com/photos/88/square.jpg",
            }
        ],
        "annotations": [{"controlled_attribute_id": 17, "controlled_value_id": 19}],
    }
    obs.update(changes)
    return obs


def test_negated_and_speculative_mentions_are_not_medical_labels():
    row = pilot.candidate(observation(), ["text_search:entangled"], {}, {})
    assert row["condition_mentions"] == ["entanglement_mention", "bleeding_mention"]
    assert row["review"]["bleeding"] is None
    assert row["review"]["entanglement"] is None
    assert row["review"]["condition_unknown"] is True
    assert row["expert_reviewed"] is False
    assert row["animal_group_hint"] == "unknown"
    assert row["community_alive_dead_annotations"][0]["value_id"] == 19
    assert "injury_present" not in row
    assert "latitude" not in row and "longitude" not in row


def test_license_filter_applies_to_actual_photo_and_observation_text():
    obs = observation(license_code="cc-by-nc")
    row = pilot.candidate(obs, [], {}, {})
    assert row["community_evidence"] == []
    assert row["condition_mentions"] == []
    assert row["condition_text_omitted_for_license"] is True
    assert row["photo"]["attribution"] == "Test creator CC BY"
    for license_code in ["cc-by-nd", "cc-by-nc", None]:
        obs["photos"][0]["license_code"] = license_code
        assert pilot.candidate(obs, [], {}, {}) is None


def test_all_shared_group_hints_are_preserved_and_missing_signs_stay_unknown():
    for group in pilot.AnimalGroup:
        row = pilot.candidate(
            observation(description="Resting", annotations=[]), [], {}, {9: group.value}
        )
        assert row["animal_group_hint"] == group.value
        assert row["condition_mentions"] == []
        assert row["review"]["visible_wound"] is None
        assert row["review"]["split"] == "unassigned_development_candidate"


def test_balancing_limits_observer_duplicates_without_erasing_groups():
    rows = [
        pilot.candidate(observation(id=i, user={"id": i % 3}), [], {i: g}, {})
        for i, g in enumerate(
            ["pinniped", "pinniped", "cetacean", "seabird", "terrestrial", "domestic_animal"],
            1,
        )
    ]
    result = pilot.balanced(rows, 5)
    assert len(result) == 5
    assert len({r["animal_group_hint"] for r in result}) == 5
    assert max(pilot.Counter(r["observer_id"] for r in result).values()) <= 2


@pytest.mark.parametrize(
    "url",
    [
        "http://static.inaturalist.org/photos/1/square.jpg",
        "https://unrelated.example/private.jpg",
        "file:///etc/passwd",
    ],
)
def test_unexpected_photo_hosts_are_not_fetched(url):
    assert pilot.photo_url({"url": url}) is None


def test_existing_review_collection_cannot_be_overwritten(tmp_path):
    (tmp_path / "candidates.jsonl").write_text("reviewed data")
    with pytest.raises(ValueError, match="preserve reviews"):
        pilot.collect(tmp_path)
    assert (tmp_path / "candidates.jsonl").read_text() == "reviewed data"


def test_only_condition_fields_are_retained():
    row = pilot.candidate(
        observation(
            ofvs=[
                {"name": "Disease/Injury?", "value": "Possible wound", "field_id": 123},
                {"name": "Private nest location", "value": "Precise coordinate text"},
            ]
        ),
        [],
        {},
        {},
    )
    fields = [e for e in row["community_evidence"] if e["kind"] == "community_field"]
    assert len(fields) == 1
    assert fields[0]["name"] == "Disease/Injury?"


def test_download_preserves_original_bytes_and_rejects_changed_snapshot(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="JPEG")
    original = buffer.getvalue()
    client = pilot.PublicClient()

    class Response:
        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield original

    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: Response())
    row = pilot.candidate(observation(), [], {}, {})
    client.download(row, tmp_path)
    file = tmp_path / row["photo"]["file"]
    assert file.read_bytes() == original
    row["photo"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="differs"):
        client.download(row, tmp_path)
    assert file.read_bytes() == original
