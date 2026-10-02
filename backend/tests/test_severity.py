"""Tests for triage scoring.

These are the most important tests in the repo. Severity decides whether a
professional team is sent, and it is pure Python, so it can be pinned exactly.
If a scoring weight changes in `config/scoring.json`, these tests should be the
thing that tells you what else moved.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from lifejacket.dispatch.severity import recommended_action, score_severity
from lifejacket.models.schemas import (
    AnimalGroup,
    EnvironmentalContext,
    GeoPoint,
    InjuryAssessment,
    MobilityConcern,
    SeverityLevel,
    SituationHazards,
    TideConditions,
    WeatherConditions,
)


@pytest.fixture
def healthy() -> InjuryAssessment:
    """An animal with nothing wrong with it."""
    return InjuryAssessment(mobility_concern=MobilityConcern.NONE)


@pytest.fixture
def no_hazards() -> SituationHazards:
    return SituationHazards()


def _context(
    *,
    wind_mph: float | None = None,
    tide_trend: str | None = None,
    coastal: bool = True,
) -> EnvironmentalContext:
    """Build an environmental context for a test case."""
    tide = None
    if tide_trend:
        now = datetime.now()
        tide = TideConditions(
            trend=tide_trend,
            next_high_tide=now + timedelta(hours=2),
            next_low_tide=now + timedelta(hours=8),
        )
    return EnvironmentalContext(
        location=GeoPoint(latitude=36.8, longitude=-121.79),
        weather=WeatherConditions(wind_speed_mph=wind_mph) if wind_mph else None,
        tide=tide,
        is_coastal=coastal,
    )


class TestHardRules:
    """Conditions that force CRITICAL regardless of the additive score."""

    def test_entanglement_alone_is_critical(self, no_hazards):
        """Entanglement scores only 1.4 additively -- the hard rule is what saves it.

        This is the case that motivates having hard rules at all: without one,
        an entangled animal with no other symptoms would be triaged "monitor"
        while the line tightens.
        """
        result = score_severity(
            injury=InjuryAssessment(entanglement=True, injury_present=True),
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
        )
        assert result.level is SeverityLevel.CRITICAL
        assert "entanglement" in result.triggered_rules

    def test_wound_with_bleeding_is_critical(self, no_hazards):
        result = score_severity(
            injury=InjuryAssessment(injury_present=True, wound=True, bleeding=True),
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
        )
        assert result.level is SeverityLevel.CRITICAL
        assert "wound_with_bleeding" in result.triggered_rules

    def test_wound_without_bleeding_is_not_a_hard_rule(self, no_hazards):
        """A wound alone goes through normal scoring, not the hard rule."""
        result = score_severity(
            injury=InjuryAssessment(injury_present=True, wound=True),
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
        )
        assert "wound_with_bleeding" not in result.triggered_rules
        # injury 1.4 + wound 1.3 = 2.7, which is below the 3.0 respond threshold
        assert result.level is SeverityLevel.MONITOR

    def test_cetacean_mobility_rule_is_group_specific(self, no_hazards):
        """An immobile cetacean is critical; an immobile pinniped is not.

        A seal resting on a beach is normal behaviour. A dolphin that cannot
        move is suffocating under its own weight.
        """
        injury = InjuryAssessment(mobility_concern=MobilityConcern.IMMOBILE)

        cetacean = score_severity(
            injury=injury, hazards=no_hazards, animal_group=AnimalGroup.CETACEAN
        )
        pinniped = score_severity(
            injury=injury, hazards=no_hazards, animal_group=AnimalGroup.PINNIPED
        )

        assert cetacean.level is SeverityLevel.CRITICAL
        assert "cetacean_mobility" in cetacean.triggered_rules
        assert pinniped.level is not SeverityLevel.CRITICAL
        assert "cetacean_mobility" not in pinniped.triggered_rules

    def test_hard_rule_carries_a_reason(self, no_hazards):
        """Every triggered rule must explain itself to the coordinator."""
        result = score_severity(
            injury=InjuryAssessment(entanglement=True),
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
        )
        assert result.reasons
        assert any("tighten" in reason.lower() for reason in result.reasons)


class TestAdditiveScoring:
    def test_healthy_animal_is_guidance_only(self, healthy, no_hazards):
        result = score_severity(
            injury=healthy, hazards=no_hazards, animal_group=AnimalGroup.PINNIPED
        )
        assert result.level is SeverityLevel.GUIDANCE
        assert result.score == 0.0
        assert not result.triggered_rules

    def test_contributions_are_itemised(self, no_hazards):
        """Each flag's points are recorded, so the console can show the maths."""
        result = score_severity(
            injury=InjuryAssessment(injury_present=True, swelling=True),
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
        )
        assert result.contributions == {"injury": 1.4, "swelling": 0.7}
        assert result.score == pytest.approx(2.1)

    def test_unknown_mobility_does_not_add_points(self, no_hazards):
        """An unanswered question must not inflate severity.

        `mobility_concern` is "unknown" whenever intake ended early. Counting
        that as a concern would make every incomplete report look worse than it
        is.
        """
        unknown = score_severity(
            injury=InjuryAssessment(mobility_concern=MobilityConcern.UNKNOWN),
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
        )
        limited = score_severity(
            injury=InjuryAssessment(mobility_concern=MobilityConcern.LIMITED),
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
        )
        assert "mobility_concern" not in unknown.contributions
        assert "mobility_concern" in limited.contributions

    def test_bystander_hazards_contribute(self, no_hazards):
        result = score_severity(
            injury=InjuryAssessment(injury_present=True),
            hazards=SituationHazards(near_people=True, near_dogs=True),
            animal_group=AnimalGroup.PINNIPED,
        )
        assert result.contributions["near_people"] == 0.6
        assert result.contributions["near_dogs"] == 0.5


class TestWeatherAdjustment:
    def test_weather_nudges_the_score(self, no_hazards):
        injury = InjuryAssessment(injury_present=True, wound=True)

        calm = score_severity(
            injury=injury, hazards=no_hazards, animal_group=AnimalGroup.PINNIPED
        )
        stormy = score_severity(
            injury=injury,
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
            context=_context(wind_mph=30),
        )
        assert stormy.score > calm.score
        assert stormy.weather_adjustment > 0

    def test_weather_adjustment_is_capped(self, healthy, no_hazards):
        """Even a hurricane adds at most `weather_adjustment.max_points`."""
        result = score_severity(
            injury=healthy,
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
            context=_context(wind_mph=90),
        )
        assert result.weather_adjustment <= 0.5

    def test_weather_alone_cannot_cause_critical(self, no_hazards):
        """The demotion guard: bad weather is never sole grounds for CRITICAL.

        Without this, a storm could escalate a moderate case to the top band
        and pull a professional team away from a real emergency.
        """
        # Flags chosen to land just *below* the 6.5 critical threshold, so that
        # only the weather bump could push the total over it. Deliberately
        # avoids wound+bleeding and respiratory distress, which are hard rules
        # and would force CRITICAL legitimately.
        injury = InjuryAssessment(
            injury_present=True,  # 1.4
            bleeding=True,  # 1.4
            mobility_concern=MobilityConcern.LIMITED,  # 1.2
            abnormal_posture=True,  # 0.9
            swelling=True,  # 0.7
        )  # condition total 5.6
        hazards = SituationHazards(near_people=True)  # +0.6 -> 6.2

        result = score_severity(
            injury=injury,
            hazards=hazards,
            animal_group=AnimalGroup.PINNIPED,
            context=_context(wind_mph=40),
        )

        # 6.2 + 0.5 weather = 6.7, which is over the 6.5 threshold -- but the
        # condition alone is not, so the guard must hold it at RESPOND.
        assert result.score > 6.5
        assert not result.triggered_rules
        assert result.level is SeverityLevel.RESPOND
        assert any("not sufficient grounds" in r for r in result.reasons)

    def test_missing_weather_adds_nothing(self, healthy, no_hazards):
        """Unknown weather must not be scored as either good or bad."""
        result = score_severity(
            injury=healthy,
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
            context=_context(wind_mph=None),
        )
        assert result.weather_adjustment == 0.0


class TestTideEscalation:
    def test_falling_tide_escalates_an_immobile_animal(self, no_hazards):
        """A falling tide is a deadline, so MONITOR becomes RESPOND."""
        injury = InjuryAssessment(mobility_concern=MobilityConcern.LIMITED)

        result = score_severity(
            injury=injury,
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
            context=_context(tide_trend="falling"),
        )
        assert result.level is SeverityLevel.RESPOND
        assert any("falling tide" in r.lower() for r in result.reasons)

    def test_tide_is_ignored_for_a_mobile_animal(self, healthy, no_hazards):
        """An animal that can move itself is not on a tidal deadline."""
        result = score_severity(
            injury=healthy,
            hazards=no_hazards,
            animal_group=AnimalGroup.PINNIPED,
            context=_context(tide_trend="falling"),
        )
        assert not any("tide" in r.lower() for r in result.reasons)

    def test_tide_is_ignored_inland(self, no_hazards):
        """Tide reasoning must not be applied to a non-coastal incident."""
        result = score_severity(
            injury=InjuryAssessment(mobility_concern=MobilityConcern.IMMOBILE),
            hazards=no_hazards,
            animal_group=AnimalGroup.TERRESTRIAL,
            context=_context(tide_trend="falling", coastal=False),
        )
        assert not any("tide" in r.lower() for r in result.reasons)


class TestConfidence:
    def test_complete_data_scores_high_confidence(self, healthy, no_hazards):
        result = score_severity(
            injury=healthy, hazards=no_hazards, animal_group=AnimalGroup.PINNIPED
        )
        assert result.confidence == 0.92

    def test_each_weakness_lowers_confidence(self, healthy, no_hazards):
        result = score_severity(
            injury=healthy,
            hazards=no_hazards,
            animal_group=AnimalGroup.UNKNOWN,
            data_quality_incomplete=True,
            data_conflict=True,
            needs_review=True,
        )
        # 0.92 - 0.25 - 0.12 - 0.12 - 0.08 = 0.35, floored at the 0.45 minimum
        assert result.confidence == 0.45

    def test_confidence_never_reaches_zero(self, healthy, no_hazards):
        """A floor exists because 0.0 would read as "ignore this incident"."""
        result = score_severity(
            injury=healthy,
            hazards=no_hazards,
            animal_group=AnimalGroup.UNKNOWN,
            data_quality_incomplete=True,
            data_conflict=True,
            needs_review=True,
        )
        assert result.confidence >= 0.45


class TestActionPolicy:
    @pytest.mark.parametrize(
        ("level", "volunteer_allowed"),
        [
            (SeverityLevel.GUIDANCE, True),
            (SeverityLevel.MONITOR, True),
            (SeverityLevel.RESPOND, False),
            (SeverityLevel.CRITICAL, False),
        ],
    )
    def test_volunteers_are_barred_from_serious_cases(self, level, volunteer_allowed):
        """A safety boundary, not a preference: untrained people must not attend."""
        assert recommended_action(level)["volunteer_allowed"] is volunteer_allowed

    def test_critical_always_requires_coordinator_review(self):
        assert recommended_action(SeverityLevel.CRITICAL)["coordinator_review_required"]
