"""Mapping a free-text species name to an animal group.

Not on the live path: the identification agent reports `animal_group`
directly. This is for text that arrives without one -- chiefly the species a
responder types into their closing log, which the evaluation notebook needs to
compare against the agent's answer at group level.

Why group matters:

Rescue organisations are permitted and equipped by animal group, not by
species: a centre authorised for pinniped rescue is not necessarily authorised
to handle a cetacean. So the exact species matters for the report, but the
group is what routes the incident.

Matching is deliberately a two-stage lookup against `config/scoring.json`:

1. **Exact match** on a known name ("harbor seal", "california sea lion").
2. **Substring fallback** on a distinctive word ("seal", "dolphin", "turtle").

The fallback is what makes this robust to the model returning a name nobody
has catalogued -- "Guadalupe fur seal" is not in the list, but "seal" is.
"""

from __future__ import annotations

import re

from lifejacket.config import load_scoring_config
from lifejacket.models.schemas import AnimalGroup

#: Group names in `scoring.json` map to our enum. Anything not listed here
#: falls through to UNKNOWN.
_GROUP_NAMES: dict[str, AnimalGroup] = {
    "pinniped": AnimalGroup.PINNIPED,
    "cetacean": AnimalGroup.CETACEAN,
    "sea_turtle": AnimalGroup.SEA_TURTLE,
    "seabird": AnimalGroup.SEABIRD,
    "other_marine": AnimalGroup.OTHER_MARINE,
    "terrestrial": AnimalGroup.TERRESTRIAL,
    "domestic_animal": AnimalGroup.DOMESTIC_ANIMAL,
}


def normalise_species(name: str | None) -> str:
    """Lower-case, strip punctuation, collapse whitespace.

    Needed because the same animal arrives as "Harbor Seal", "harbour seal",
    and "Harbor seal (Phoca vitulina)" depending on which agent produced it.
    """
    if not name:
        return ""
    cleaned = re.sub(r"\(.*?\)", " ", name.lower())  # drop scientific names
    cleaned = re.sub(r"[^a-z\s-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def group_from_species(species_name: str | None) -> AnimalGroup:
    """Classify a species name into an `AnimalGroup`.

    Returns UNKNOWN rather than guessing when nothing matches. Downstream, an
    unknown group widens the dispatch search instead of narrowing it to the
    wrong specialists.
    """
    name = normalise_species(species_name)
    if not name:
        return AnimalGroup.UNKNOWN

    config = load_scoring_config()

    # Stage 1: exact match against the catalogued name lists.
    for group_key, names in config["species_groups"].items():
        if name in {normalise_species(n) for n in names}:
            return _GROUP_NAMES.get(group_key, AnimalGroup.UNKNOWN)

    # Stage 2: substring fallback on distinctive words.
    substring_terms = config["species_grouping"]["substring_terms"]
    for group_key, terms in substring_terms.items():
        if any(term in name for term in terms):
            return _GROUP_NAMES.get(group_key, AnimalGroup.UNKNOWN)

    return AnimalGroup.UNKNOWN
