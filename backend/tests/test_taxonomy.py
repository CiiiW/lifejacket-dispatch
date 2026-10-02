"""Tests for pooling species probabilities up the taxonomy."""

from __future__ import annotations

import pytest
from lifejacket.models.schemas import AnimalGroup, SpeciesCandidate, TaxonRank
from lifejacket.taxonomy import describe_resolution, normalise_candidates, resolve_taxon

THRESHOLD = 0.90


def _c(name, scientific, p, family=None, group=AnimalGroup.CETACEAN, **kw):
    return SpeciesCandidate(
        common_name=name,
        scientific_name=scientific,
        confidence=p,
        family=family,
        animal_group=group,
        **kw,
    )


def test_single_confident_species_resolves_at_species():
    r = resolve_taxon([_c("Harbor seal", "Phoca vitulina", 0.94, "Phocidae")], THRESHOLD)
    assert r.rank is TaxonRank.SPECIES
    assert r.name == "Harbor seal"
    assert r.meets_threshold


def test_two_species_in_one_genus_pool_to_genus():
    r = resolve_taxon(
        [
            _c("Long-beaked common dolphin", "Delphinus capensis", 0.5,
               genus_common_name="common dolphins"),
            _c("Short-beaked common dolphin", "Delphinus delphis", 0.45),
        ],
        THRESHOLD,
    )
    assert r.rank is TaxonRank.GENUS
    assert r.scientific_name == "Delphinus"
    assert r.name == "Common dolphins"
    assert r.confidence == pytest.approx(0.95)


def test_common_and_bottlenose_dolphin_pool_to_family():
    """Different genera (Delphinus, Tursiops), same family (Delphinidae)."""
    r = resolve_taxon(
        [
            _c("Common dolphin", "Delphinus delphis", 0.50, "Delphinidae",
               family_common_name="oceanic dolphins"),
            _c("Bottlenose dolphin", "Tursiops truncatus", 0.44, "Delphinidae",
               family_common_name="oceanic dolphins"),
        ],
        THRESHOLD,
    )
    assert r.rank is TaxonRank.FAMILY
    assert r.name == "Oceanic dolphins"
    assert r.animal_group is AnimalGroup.CETACEAN
    # The per-species probabilities survive for the report.
    assert [(m.common_name, m.confidence) for m in r.members] == [
        ("Common dolphin", 0.50),
        ("Bottlenose dolphin", 0.44),
    ]


def test_finest_confident_rank_wins():
    """A confident species is not blurred up to its family."""
    r = resolve_taxon(
        [
            _c("Common dolphin", "Delphinus delphis", 0.92, "Delphinidae"),
            _c("Bottlenose dolphin", "Tursiops truncatus", 0.05, "Delphinidae"),
        ],
        THRESHOLD,
    )
    assert r.rank is TaxonRank.SPECIES


def test_falls_back_to_animal_group():
    r = resolve_taxon(
        [
            _c("Common dolphin", "Delphinus delphis", 0.50, "Delphinidae"),
            _c("Harbour porpoise", "Phocoena phocoena", 0.45, "Phocoenidae"),
        ],
        THRESHOLD,
    )
    assert r.rank is TaxonRank.GROUP
    assert r.name == "Whale, dolphin, or porpoise"


def test_nothing_confident_returns_best_guess_marked_unconfident():
    r = resolve_taxon(
        [
            _c("Harbor seal", "Phoca vitulina", 0.40, "Phocidae", AnimalGroup.PINNIPED),
            _c("Common dolphin", "Delphinus delphis", 0.30, "Delphinidae"),
        ],
        THRESHOLD,
    )
    assert r.rank is TaxonRank.SPECIES
    assert r.name == "Harbor seal"
    assert not r.meets_threshold


def test_no_candidates_returns_none():
    assert resolve_taxon([], THRESHOLD) is None


def test_missing_genus_is_recovered_from_scientific_name():
    [c] = normalise_candidates([_c("Harbor seal", "Phoca vitulina", 0.5)])
    assert c.genus == "Phoca"


def test_probabilities_summing_over_one_are_rescaled():
    """Otherwise pooling could report a family at 1.2."""
    cleaned = normalise_candidates(
        [_c("A", "Aa aa", 0.7, "F"), _c("B", "Bb bb", 0.5, "F")]
    )
    assert sum(c.confidence for c in cleaned) == pytest.approx(1.0, abs=1e-3)


def test_probabilities_summing_under_one_are_left_alone():
    """Leftover mass means "something not on this list" -- do not inflate it."""
    cleaned = normalise_candidates([_c("A", "Aa aa", 0.5), _c("B", "Bb bb", 0.2)])
    assert [c.confidence for c in cleaned] == [0.5, 0.2]


def test_description_includes_species_probabilities():
    r = resolve_taxon(
        [
            _c("Common dolphin", "Delphinus delphis", 0.50, "Delphinidae",
               family_common_name="oceanic dolphins"),
            _c("Bottlenose dolphin", "Tursiops truncatus", 0.44, "Delphinidae"),
        ],
        THRESHOLD,
    )
    text = describe_resolution(r)
    assert "family level" in text
    assert "common dolphin 0.50" in text
    assert "bottlenose dolphin 0.44" in text
