"""Tests for duplicate detection, responder matching, species grouping, and geo."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from lifejacket.dispatch.duplicates import (
    CandidateIncident,
    duplicate_confidence,
    find_duplicate,
    is_possible_duplicate,
    is_probable_duplicate,
)
from lifejacket.dispatch.matching import (
    infer_needs_live_response,
    load_rescue_centers,
    rank_centers,
    score_area_match,
    score_capability_match,
)
from lifejacket.dispatch.species import group_from_species, normalise_species
from lifejacket.geo import bounding_box, haversine_km
from lifejacket.models.schemas import AnimalGroup, InjuryAssessment, MobilityConcern


class TestGeo:
    def test_known_distance(self):
        """San Francisco to Los Angeles is about 559 km."""
        distance = haversine_km(37.7749, -122.4194, 34.0522, -118.2437)
        assert distance == pytest.approx(559, abs=5)

    def test_zero_distance(self):
        assert haversine_km(36.8, -121.79, 36.8, -121.79) == pytest.approx(0, abs=1e-9)

    def test_bounding_box_contains_the_radius(self):
        min_lat, max_lat, min_lon, max_lon = bounding_box(36.8, -121.79, 10.0)
        assert min_lat < 36.8 < max_lat
        assert min_lon < -121.79 < max_lon
        # The box must be at least as large as the circle, or the SQL
        # pre-filter would exclude rows that are genuinely in range.
        assert haversine_km(36.8, -121.79, max_lat, -121.79) >= 10.0

    def test_bounding_box_survives_the_poles(self):
        """cos(latitude) approaches zero at the poles and would divide by it."""
        min_lat, max_lat, min_lon, max_lon = bounding_box(89.99, 0.0, 50.0)
        assert all(isinstance(v, float) for v in (min_lat, max_lat, min_lon, max_lon))


class TestSpeciesGrouping:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Harbor seal", AnimalGroup.PINNIPED),
            ("California sea lion", AnimalGroup.PINNIPED),
            ("Common dolphin", AnimalGroup.CETACEAN),
            ("Harbour porpoise", AnimalGroup.CETACEAN),
            ("Loggerhead sea turtle", AnimalGroup.SEA_TURTLE),
        ],
    )
    def test_catalogued_names_match_exactly(self, name, expected):
        assert group_from_species(name) is expected

    def test_uncatalogued_name_falls_back_to_substring(self):
        """"Guadalupe fur seal" is not in the list, but "seal" is.

        This fallback is what makes grouping robust to the model returning a
        species nobody thought to catalogue.
        """
        assert group_from_species("Guadalupe fur seal") is AnimalGroup.PINNIPED
        assert group_from_species("Risso's dolphin") is AnimalGroup.CETACEAN

    def test_scientific_name_in_parentheses_is_ignored(self):
        assert group_from_species("Harbor seal (Phoca vitulina)") is AnimalGroup.PINNIPED

    def test_unrecognised_name_is_unknown_not_a_guess(self):
        assert group_from_species("some kind of animal") is AnimalGroup.UNKNOWN
        assert group_from_species(None) is AnimalGroup.UNKNOWN

    def test_normalisation(self):
        assert normalise_species("  Harbor   SEAL!  ") == "harbor seal"

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Western gull", AnimalGroup.SEABIRD),
            ("Sea otter", AnimalGroup.OTHER_MARINE),
            ("Raccoon", AnimalGroup.TERRESTRIAL),
            ("Coyote", AnimalGroup.TERRESTRIAL),
            ("Domestic dog", AnimalGroup.DOMESTIC_ANIMAL),
        ],
    )
    def test_non_marine_mammal_names_still_resolve_to_a_real_group(self, name, expected):
        """Any animal gets a specific group, not just the original five."""
        assert group_from_species(name) is expected


class TestDuplicateDetection:
    def test_same_spot_same_minute_scores_very_high(self):
        assert duplicate_confidence(0.0, 0.0, True) == pytest.approx(1.0)

    def test_distance_decays_to_the_cut_off(self):
        """At the 1 km limit, distance contributes nothing."""
        near = duplicate_confidence(0.1, 1.0, True)
        far = duplicate_confidence(1.0, 1.0, True)
        assert near > far

    def test_species_mismatch_is_a_partial_penalty_not_a_veto(self):
        """Reporters describe the same animal inconsistently.

        A mismatch should weaken the match, not disqualify it outright.
        """
        same = duplicate_confidence(0.05, 0.5, True)
        different = duplicate_confidence(0.05, 0.5, False)
        assert different < same
        assert different > 0.6  # still a strong match on distance and time

    def test_nearby_recent_report_is_matched(self):
        now = datetime.now()
        match = find_duplicate(
            latitude=36.8000,
            longitude=-121.7900,
            reported_at=now,
            animal_group=AnimalGroup.PINNIPED,
            candidates=[
                CandidateIncident(
                    incident_id="INC_earlier",
                    latitude=36.8003,
                    longitude=-121.7902,
                    reported_at=now - timedelta(minutes=20),
                    animal_group=AnimalGroup.PINNIPED,
                )
            ],
        )
        assert match is not None
        assert match.incident_id == "INC_earlier"
        assert is_probable_duplicate(match)

    def test_report_outside_the_distance_window_is_not_matched(self):
        now = datetime.now()
        match = find_duplicate(
            latitude=36.80,
            longitude=-121.79,
            reported_at=now,
            animal_group=AnimalGroup.PINNIPED,
            candidates=[
                CandidateIncident(
                    incident_id="INC_far",
                    latitude=37.50,  # ~78 km away
                    longitude=-122.20,
                    reported_at=now,
                    animal_group=AnimalGroup.PINNIPED,
                )
            ],
        )
        assert match is None

    def test_report_outside_the_time_window_is_not_matched(self):
        now = datetime.now()
        match = find_duplicate(
            latitude=36.80,
            longitude=-121.79,
            reported_at=now,
            animal_group=AnimalGroup.PINNIPED,
            candidates=[
                CandidateIncident(
                    incident_id="INC_old",
                    latitude=36.80,
                    longitude=-121.79,
                    reported_at=now - timedelta(days=3),
                    animal_group=AnimalGroup.PINNIPED,
                )
            ],
        )
        assert match is None

    def test_unknown_group_is_compatible_with_anything(self):
        """No evidence of a mismatch is not evidence of one."""
        now = datetime.now()
        match = find_duplicate(
            latitude=36.80,
            longitude=-121.79,
            reported_at=now,
            animal_group=AnimalGroup.UNKNOWN,
            candidates=[
                CandidateIncident(
                    incident_id="INC_a",
                    latitude=36.8001,
                    longitude=-121.7901,
                    reported_at=now,
                    animal_group=AnimalGroup.CETACEAN,
                )
            ],
        )
        assert match is not None
        assert match.same_species

    def test_different_animal_groups_are_flagged_but_never_suppressed(self):
        """A dolphin 200 m from a seal, an hour later, is not the same animal.

        Distance and time alone clear the 0.70 threshold here, so without the
        group check the second animal's report would be cancelled.
        """
        now = datetime.now()
        match = find_duplicate(
            latitude=36.8000,
            longitude=-121.7900,
            reported_at=now,
            animal_group=AnimalGroup.CETACEAN,
            candidates=[
                CandidateIncident(
                    incident_id="INC_seal",
                    latitude=36.8018,  # ~200 m north
                    longitude=-121.7900,
                    reported_at=now - timedelta(hours=1),
                    animal_group=AnimalGroup.PINNIPED,
                )
            ],
        )
        assert match is not None  # still recorded, for the coordinator
        assert not match.same_species
        assert match.confidence >= 0.70  # the score alone would have suppressed it
        assert not is_probable_duplicate(match)
        assert is_possible_duplicate(match)  # shown to the coordinator instead

    def test_unknown_group_does_not_block_suppression(self):
        """Unknown is not a disagreement: a close, recent match still suppresses."""
        now = datetime.now()
        match = find_duplicate(
            latitude=36.80,
            longitude=-121.79,
            reported_at=now,
            animal_group=AnimalGroup.UNKNOWN,
            candidates=[
                CandidateIncident(
                    incident_id="INC_a",
                    latitude=36.8001,
                    longitude=-121.7901,
                    reported_at=now - timedelta(minutes=10),
                    animal_group=AnimalGroup.CETACEAN,
                )
            ],
        )
        assert is_probable_duplicate(match)

    def test_a_linkable_match_outranks_a_closer_one_that_cannot_be_linked(self):
        """A dolphin right here and the same seal a little further off.

        The dolphin scores higher on distance, but it can never be linked to a
        seal report. Picking it would dispatch a second team to the seal.
        """
        now = datetime.now()
        match = find_duplicate(
            latitude=36.8000,
            longitude=-121.7900,
            reported_at=now,
            animal_group=AnimalGroup.PINNIPED,
            candidates=[
                CandidateIncident(
                    incident_id="INC_dolphin",
                    latitude=36.8000,
                    longitude=-121.7900,
                    reported_at=now - timedelta(minutes=5),
                    animal_group=AnimalGroup.CETACEAN,
                ),
                CandidateIncident(
                    incident_id="INC_seal",
                    latitude=36.8027,  # ~300 m north
                    longitude=-121.7900,
                    reported_at=now - timedelta(hours=1),
                    animal_group=AnimalGroup.PINNIPED,
                ),
            ],
        )
        assert match.incident_id == "INC_seal"
        assert is_probable_duplicate(match)

    def test_weak_match_is_neither_linked_nor_shown(self):
        """Same beach, most of a day apart: recorded, but not worth a banner."""
        now = datetime.now()
        match = find_duplicate(
            latitude=36.8000,
            longitude=-121.7900,
            reported_at=now,
            animal_group=AnimalGroup.PINNIPED,
            candidates=[
                CandidateIncident(
                    incident_id="INC_yesterday",
                    latitude=36.8063,  # ~700 m north
                    longitude=-121.7900,
                    reported_at=now - timedelta(hours=20),
                    animal_group=AnimalGroup.PINNIPED,
                )
            ],
        )
        assert match is not None
        assert not is_probable_duplicate(match)
        assert not is_possible_duplicate(match)

    def test_a_linked_match_is_not_also_a_possible_one(self):
        now = datetime.now()
        candidate = CandidateIncident(
            incident_id="INC_a",
            latitude=36.80,
            longitude=-121.79,
            reported_at=now - timedelta(minutes=10),
            animal_group=AnimalGroup.PINNIPED,
        )
        match = find_duplicate(36.80, -121.79, now, AnimalGroup.PINNIPED, [candidate])
        assert is_probable_duplicate(match)
        assert not is_possible_duplicate(match)
        assert not is_possible_duplicate(None)

    def test_missing_location_declines_to_guess(self):
        assert (
            find_duplicate(None, None, datetime.now(), AnimalGroup.PINNIPED, [])
            is None
        )


class TestResponderMatching:
    def test_directory_loads(self):
        centers = load_rescue_centers()
        assert len(centers) > 20
        assert all(c.center_name for c in centers)

    def test_area_match_needs_overlap(self):
        area = "Del Norte and Humboldt Counties, California"
        assert score_area_match(area, ["humboldt"]) > 0
        assert score_area_match(area, ["san diego"]) == 0.0

    def test_more_matching_terms_scores_higher(self):
        area = "Del Norte and Humboldt Counties, California"
        assert score_area_match(area, ["humboldt", "california"]) > score_area_match(
            area, ["humboldt"]
        )

    def test_area_match_is_capped_at_one(self):
        area = "Del Norte and Humboldt Counties, California"
        score = score_area_match(area, ["del norte", "humboldt", "california"])
        assert score <= 1.0

    def test_dead_only_centre_is_penalised_for_a_live_call(self):
        """Sending a carcass-recovery team to a living animal is a real failure."""
        live_capable, _ = score_capability_match(
            "Live Pinniped Rescue and Rehabilitation",
            AnimalGroup.PINNIPED,
            needs_live_response=True,
            injury=InjuryAssessment(),
        )
        dead_only, _ = score_capability_match(
            "Dead Cetacean, Pinniped, and Sea Turtle Response",
            AnimalGroup.PINNIPED,
            needs_live_response=True,
            injury=InjuryAssessment(),
        )
        assert live_capable > dead_only

    def test_entanglement_prefers_a_capable_team(self):
        entangled = InjuryAssessment(entanglement=True, injury_present=True)

        with_capability, matched = score_capability_match(
            "Live Cetacean Response; Whale Entanglement Response",
            AnimalGroup.CETACEAN,
            needs_live_response=True,
            injury=entangled,
        )
        without, _ = score_capability_match(
            "Live Cetacean Response",
            AnimalGroup.CETACEAN,
            needs_live_response=True,
            injury=entangled,
        )
        assert with_capability > without
        assert any("entanglement" in m for m in matched)

    def test_unknown_species_prefers_a_generalist(self):
        score, matched = score_capability_match(
            "General marine mammal response",
            AnimalGroup.UNKNOWN,
            needs_live_response=True,
            injury=InjuryAssessment(),
        )
        assert score > 0
        assert any("general" in m for m in matched)

    def test_ranking_returns_scored_candidates_with_rationale(self):
        candidates = rank_centers(
            area_terms=["humboldt", "california"],
            animal_group=AnimalGroup.PINNIPED,
            injury=InjuryAssessment(injury_present=True, wound=True),
        )
        assert candidates
        assert candidates[0].score >= candidates[-1].score  # sorted
        # Every candidate must justify itself: coordinators approve reasons,
        # not numbers.
        assert all(c.rationale for c in candidates)

    def test_unmatched_area_still_returns_one_option(self):
        """A weak match with a clear rationale beats returning nothing."""
        candidates = rank_centers(
            area_terms=["nowhere in the directory"],
            animal_group=AnimalGroup.PINNIPED,
            injury=InjuryAssessment(),
        )
        assert len(candidates) <= 1

    def test_live_response_is_the_conservative_default(self):
        assert infer_needs_live_response(InjuryAssessment())
        assert infer_needs_live_response(
            InjuryAssessment(mobility_concern=MobilityConcern.UNKNOWN)
        )

    def test_deceased_requires_unresponsive_and_immobile(self):
        assert not infer_needs_live_response(
            InjuryAssessment(unresponsive=True, mobility_concern=MobilityConcern.IMMOBILE)
        )

    def test_absence_of_respiratory_distress_does_not_imply_death(self):
        """A false flag means "not observed", not "confirmed not breathing"."""
        assert infer_needs_live_response(
            InjuryAssessment(unresponsive=True, respiratory_distress=False)
        )

    @pytest.mark.parametrize("group", [AnimalGroup.TERRESTRIAL, AnimalGroup.DOMESTIC_ANIMAL])
    def test_no_responder_is_suggested_for_a_group_this_directory_cannot_serve(self, group):
        """The directory is marine-mammal-only; a coyote must not get a seal centre.

        Area terms here deliberately match real counties in the directory, so
        if the group guard were missing, area-only scoring would still produce
        a (wrong) match. An empty list is the only honest answer.
        """
        candidates = rank_centers(
            area_terms=["humboldt", "california"],
            animal_group=group,
            injury=InjuryAssessment(injury_present=True, abnormal_posture=True),
        )
        assert candidates == []

    def test_other_marine_matches_a_generic_marine_mammal_centre(self):
        """A sea otter has no dedicated permit text, but "marine mammal" responders exist."""
        score, matched = score_capability_match(
            "Live and Dead Marine Mammal Stranding Response",
            AnimalGroup.OTHER_MARINE,
            needs_live_response=True,
            injury=InjuryAssessment(),
        )
        assert score > 0
        assert any("other_marine" in m for m in matched)

    def test_other_marine_can_still_be_ranked(self):
        """Unlike terrestrial/domestic, other_marine is a real, scoreable group."""
        candidates = rank_centers(
            area_terms=["humboldt", "california"],
            animal_group=AnimalGroup.OTHER_MARINE,
            injury=InjuryAssessment(),
        )
        assert candidates
        assert all(c.rationale for c in candidates)
