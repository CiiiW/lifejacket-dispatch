"""Saved stills must not publish invented environmental context or deadlines."""

from types import SimpleNamespace

import pytest
from lifejacket.models.schemas import AnimalGroup, AssessmentResult, GeoPoint
from lifejacket.services import drone_vision


@pytest.mark.parametrize("known_time", [False, True])
@pytest.mark.parametrize("known_location", [False, True])
def test_unverified_environment_is_withheld_without_losing_visible_injury(
    monkeypatch, known_time, known_location
):
    calls = {}
    original_rationale = "Outside nesting season, falling tide leaves two hours to rescue."
    assessment = AssessmentResult(
        environmental_rationale=original_rationale,
        time_sensitivity_hours=2.0,
        recommended_action="A permitted rescue team should review the visible wound.",
    )
    assessment.injury.mobility_concern = type(assessment.injury.mobility_concern).IMMOBILE
    assessment.injury.unresponsive = True
    assessment.injury.wound = True
    assessment.injury.bleeding = True
    assessment.injury.injury_present = True
    identification = SimpleNamespace(
        animal_group=AnimalGroup.SEA_TURTLE,
        display_name="Green Sea Turtle",
        confidence=0.9,
        is_confident=True,
        model_dump=lambda **_: {"animal_group": "sea_turtle"},
    )

    class Identifier:
        def __init__(self, client):
            self.client = SimpleNamespace(model="fixture")
            self.last_metrics = {}

        def run(self, **kwargs):
            calls["identification"] = kwargs
            return identification

    class Assessor:
        def __init__(self, client):
            self.last_metrics = {}

        def run(self, **kwargs):
            calls["assessment"] = kwargs
            return assessment

    monkeypatch.setattr(drone_vision, "IdentificationAgent", Identifier)
    monkeypatch.setattr(drone_vision, "AssessmentAgent", Assessor)
    result = drone_vision.analyze_still(
        object(),
        1,
        observed_at="2026-06-01T12:00:00Z" if known_time else None,
        location=GeoPoint(latitude=1, longitude=1, source="manual_entry")
        if known_location
        else None,
    )
    accepted = result["assessment"]
    assert "Outside nesting season" not in accepted["environmental_rationale"]
    assert "falling tide" not in accepted["environmental_rationale"]
    assert "unverified" in accepted["environmental_rationale"]
    assert accepted["time_sensitivity_hours"] is None
    assert accepted["injury"]["mobility_concern"] == "unknown"
    assert accepted["injury"]["unresponsive"] is False
    assert accepted["next_question"] is None
    assert accepted["is_confident"] is False
    assert accepted["injury"]["wound"] and accepted["injury"]["bleeding"]
    assert accepted["recommended_action"].endswith("visible wound.")
    assert accepted["requires_human_review"] is True
    audit = result["context_validation"]
    assert audit["withheld_model_fields"]["environmental_rationale"] == original_rationale
    assert audit["withheld_model_fields"]["time_sensitivity_hours"] == 2.0
    assert audit["capture_time_known"] is known_time
    assert audit["location_provided"] is known_location
    prompt = calls["assessment"]["environment_summary"]
    assert "local nesting context: unavailable" in prompt
    assert calls["assessment"]["questions_remaining"] == 0
    if not known_time:
        assert "Capture time: unknown" in prompt
    if not known_location:
        assert "Location: unknown" in prompt


def test_stillness_alone_is_not_accepted_as_injury(monkeypatch):
    assessment = AssessmentResult()
    assessment.injury.injury_present = True
    assessment.injury.mobility_concern = type(assessment.injury.mobility_concern).IMMOBILE
    assessment.injury.unresponsive = True
    identification = SimpleNamespace(
        animal_group=AnimalGroup.SEA_TURTLE,
        display_name="Green Sea Turtle",
        confidence=0.9,
        is_confident=True,
        model_dump=lambda **_: {},
    )

    class Stub:
        client = SimpleNamespace(model="fixture")
        last_metrics = {}

        def __init__(self, _):
            pass

        def run(self, **kwargs):
            return identification

    class Assessor(Stub):
        def run(self, **kwargs):
            return assessment

    monkeypatch.setattr(drone_vision, "IdentificationAgent", Stub)
    monkeypatch.setattr(drone_vision, "AssessmentAgent", Assessor)
    result = drone_vision.analyze_still(object(), 1)
    assert result["assessment"]["injury"]["injury_present"] is False
    assert result["assessment"]["injury"]["mobility_concern"] == "unknown"
    assert result["assessment"]["requires_human_review"] is True
    assert (
        result["context_validation"]["withheld_model_fields"]["mobility_concern"] == "immobile"
    )
