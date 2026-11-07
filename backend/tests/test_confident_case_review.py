"""The live research recheck must never substitute an unverified input."""

import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "scripts/review_confident_cases.py"
spec = importlib.util.spec_from_file_location("confident_case_review", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def source(tmp_path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"original-photo")
    return {
        "case_id": "enhydra_lutris_02",
        "manifest_photo_attached": True,
        "reference_species": "Enhydra lutris",
        "current_taxon_name": "Enhydra lutris nereis",
        "download_file": str(photo),
        "download_sha256": module.sha(photo.read_bytes()),
    }


def test_verified_subspecies_is_accepted(tmp_path):
    row = source(tmp_path)
    _, data = module.verify_source(row)
    assert data == b"original-photo"


@pytest.mark.parametrize(
    "failure", ["foreign_case", "unattached", "wrong_taxon", "changed_bytes"]
)
def test_unverified_inputs_are_rejected(tmp_path, failure):
    row = source(tmp_path)
    if failure == "foreign_case":
        row["case_id"] = "not-approved"
    elif failure == "unattached":
        row["manifest_photo_attached"] = False
    elif failure == "wrong_taxon":
        row["current_taxon_name"] = "Zalophus californianus"
    else:
        Path(row["download_file"]).write_bytes(b"replacement")
    with pytest.raises(ValueError):
        module.verify_source(row)
