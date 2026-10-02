"""Deciding *how specifically* an animal has been identified.

The identification agent returns per-species probabilities, for example:

    Common dolphin      (Delphinus delphis)    0.48   family Delphinidae
    Bottlenose dolphin  (Tursiops truncatus)   0.41   family Delphinidae
    Harbour porpoise    (Phocoena phocoena)    0.06   family Phocoenidae

Neither dolphin reaches the 0.90 threshold on its own, so a species-level
answer would be "unconfident". But they share a family, and together they hold
0.89 -- and once the porpoise is ruled out, more. "Oceanic dolphin" is a
perfectly good answer to route a rescue on: the same teams respond to both
species, and a responder will tell them apart on the beach.

`resolve_taxon` does this pooling. It walks up the tree -- species, genus,
family, animal group -- and returns the **finest rank whose pooled probability
clears the threshold**. The individual species probabilities are kept on the
result (`members`) so the report can still say "common 0.48 / bottlenose 0.41".

This is plain Python, not a model decision, for the same reason severity is:
the rule must be identical on every incident, and testable without an API key.

A note on the dolphin example: common and bottlenose dolphins are different
*genera* (Delphinus, Tursiops), so "dolphin" is a family-level answer, not a
genus-level one. Whether the chatbot may stop asking at family level is set by
`settings.confident_taxon_ranks` -- see `chatbot/session.py`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from lifejacket.models.schemas import (
    AnimalGroup,
    SpeciesCandidate,
    TaxonRank,
    TaxonResolution,
)

#: Labels for the coarsest rank, used when even the family is uncertain.
GROUP_LABELS: dict[AnimalGroup, str] = {
    AnimalGroup.PINNIPED: "Seal or sea lion",
    AnimalGroup.CETACEAN: "Whale, dolphin, or porpoise",
    AnimalGroup.SEA_TURTLE: "Sea turtle",
    AnimalGroup.SEABIRD: "Seabird",
    AnimalGroup.OTHER_MARINE: "Marine animal",
    AnimalGroup.TERRESTRIAL: "Wild land animal",
    AnimalGroup.DOMESTIC_ANIMAL: "Domestic animal",
}


def normalise_candidates(candidates: list[SpeciesCandidate]) -> list[SpeciesCandidate]:
    """Clean up the model's candidates so they can be pooled reliably.

    Two repairs:

    1. **Fill in a missing genus** from the scientific name. "Phoca vitulina"
       is genus Phoca by definition, so a blank genus field is recoverable.
    2. **Rescale probabilities that sum to more than 1.** Models occasionally
       return 0.7 + 0.5. Left alone, pooling would report a family at 1.2.
       Totals *under* 1 are left as they are: the missing mass means "something
       not on this list", and inflating it would overstate confidence.
    """
    cleaned: list[SpeciesCandidate] = []
    for candidate in candidates:
        genus = (candidate.genus or "").strip()
        if not genus and candidate.scientific_name:
            genus = candidate.scientific_name.strip().split()[0]
        cleaned.append(
            candidate.model_copy(
                update={
                    "genus": genus.capitalize() or None,
                    "family": (candidate.family or "").strip().capitalize() or None,
                }
            )
        )

    total = sum(c.confidence for c in cleaned)
    if total > 1.0:
        cleaned = [
            c.model_copy(update={"confidence": round(c.confidence / total, 4)})
            for c in cleaned
        ]
    return cleaned


def resolve_taxon(
    candidates: list[SpeciesCandidate], threshold: float
) -> TaxonResolution | None:
    """Return the finest taxon whose pooled probability reaches `threshold`.

    If no rank reaches it, returns the single most likely species with
    `meets_threshold=False` -- an honest best guess, which the report states
    as uncertain. Returns None only when there are no candidates at all.
    """
    candidates = normalise_candidates(candidates)
    if not candidates:
        return None

    # (rank, how to find a candidate's taxon at that rank)
    ladder: list[tuple[TaxonRank, Callable[[SpeciesCandidate], str | None]]] = [
        (TaxonRank.SPECIES, lambda c: (c.scientific_name or c.common_name).lower()),
        (TaxonRank.GENUS, lambda c: c.genus),
        (TaxonRank.FAMILY, lambda c: c.family),
        (TaxonRank.GROUP, _known_group),
    ]

    for rank, key_of in ladder:
        pools: dict[str, list[SpeciesCandidate]] = defaultdict(list)
        for candidate in candidates:
            key = key_of(candidate)
            if key:
                pools[key].append(candidate)
        if not pools:
            continue

        members = max(pools.values(), key=_pooled)
        if _pooled(members) >= threshold:
            return _build(rank, members, meets_threshold=True)

    # Nothing confident at any rank: report the top species as a best guess.
    top = max(candidates, key=lambda c: c.confidence)
    return _build(TaxonRank.SPECIES, [top], meets_threshold=False)


def _known_group(candidate: SpeciesCandidate) -> str | None:
    if candidate.animal_group is AnimalGroup.UNKNOWN:
        return None
    return candidate.animal_group.value


def _pooled(members: list[SpeciesCandidate]) -> float:
    return min(sum(c.confidence for c in members), 1.0)


def _build(
    rank: TaxonRank, members: list[SpeciesCandidate], *, meets_threshold: bool
) -> TaxonResolution:
    """Assemble a resolution with a human-readable name for its rank."""
    members = sorted(members, key=lambda c: c.confidence, reverse=True)
    lead = members[0]

    if rank is TaxonRank.SPECIES:
        name, scientific = lead.common_name, lead.scientific_name
    elif rank is TaxonRank.GENUS:
        name = lead.genus_common_name or f"{lead.genus} species"
        scientific = lead.genus
    elif rank is TaxonRank.FAMILY:
        name = lead.family_common_name or lead.family or "Unknown family"
        scientific = lead.family
    else:
        name = GROUP_LABELS.get(lead.animal_group, "Unidentified animal")
        scientific = None

    return TaxonResolution(
        rank=rank,
        name=_capitalise(name),
        scientific_name=scientific,
        confidence=round(_pooled(members), 4),
        animal_group=_group_of(members),
        meets_threshold=meets_threshold,
        members=members,
    )


def _group_of(members: list[SpeciesCandidate]) -> AnimalGroup:
    """The animal group of a pooled taxon -- the most probable member's group."""
    known = [m for m in members if m.animal_group is not AnimalGroup.UNKNOWN]
    if not known:
        return AnimalGroup.UNKNOWN
    return max(known, key=lambda m: m.confidence).animal_group


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def describe_resolution(resolution: TaxonResolution | None) -> str:
    """One line for prompts and reports, e.g.

    "Oceanic dolphins (Delphinidae), identified to family level, 0.89
     confident -- common dolphin 0.48, bottlenose dolphin 0.41"
    """
    if resolution is None:
        return "Animal not identified."

    sci = f" ({resolution.scientific_name})" if resolution.scientific_name else ""
    certainty = "confident" if resolution.meets_threshold else "NOT confident -- best guess"
    line = (
        f"{resolution.name}{sci}, identified to {resolution.rank.value} level, "
        f"{resolution.confidence:.2f} ({certainty})"
    )
    if resolution.rank is not TaxonRank.SPECIES or len(resolution.members) > 1:
        breakdown = ", ".join(
            f"{m.common_name.lower()} {m.confidence:.2f}" for m in resolution.members
        )
        line += f" -- species probabilities: {breakdown}"
    return line
