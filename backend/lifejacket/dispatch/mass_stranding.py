"""Is this one animal, or the edge of something much larger?

A mass stranding is "two or more cetaceans (same or mixed species) at the same
time and place (other than cow-calf pairs)" -- NOAA, *Cetacean Mass Stranding
Policies and Best Practices* (2022). It needs a different response from a
single animal: more people, more equipment, someone coordinating on the beach.
A coordinator who learns the scale from the fourth separate notification has
already sent the wrong response to the first three.

Nothing else in the pipeline can see this, because every other step looks at
one report at a time. Duplicate detection makes it harder still: five people
reporting three dolphins looks, report by report, like one dolphin and four
duplicates.

How the count is built
----------------------
Two things can show that there is more than one animal:

1. **One report says so.** The assessment agent records `animal_count` from
   the photos and what the reporter said.
2. **Separate incidents are close together.** Two reports that duplicate
   detection did *not* link (too far apart, or too long apart, to be the same
   animal) but that are still on the same stretch of coast on the same day.

So, over the incidents that are open right now:

- An incident and the duplicates linked to it are one group of reporters
  looking at one scene. Its count is the **largest** count any of them gave.
  Not the sum: the same animals appear in several people's photos.
- Separate incidents close in place and time are joined into one event, and
  their counts are **added**. The system already decided those are different
  animals when it declined to link them.
- An event with `min_animals` or more is a mass stranding.

Events are joined by chaining (A is near B, B is near C, so A, B and C are one
event) so that every incident in an event reports the same event. Animals
strand along a beach, not in a circle around the first one found.

What this cannot see
--------------------
Two people who each photograph a *different* single dolphin 100 m apart, and
neither mentions the other animal: the second report is linked as a duplicate,
both say one animal, and the count stays at one. Telling those apart needs the
photos compared, which is not built.

Only groups listed in the config count (cetaceans). Several seals on one beach
is a haul-out, which is what seals do.

Deterministic, no model call, and never stored: a new report changes the
answer for every incident in the event, so callers compute it when asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from lifejacket.config import load_scoring_config
from lifejacket.geo import haversine_km
from lifejacket.models.schemas import AnimalGroup, MassStranding

_GROUP_NAMES = {
    AnimalGroup.CETACEAN: "whales, dolphins or porpoises",
    AnimalGroup.PINNIPED: "seals or sea lions",
    AnimalGroup.SEA_TURTLE: "sea turtles",
    AnimalGroup.SEABIRD: "seabirds",
}


@dataclass(frozen=True)
class StrandingReport:
    """One report, reduced to what scale detection needs."""

    incident_id: str
    latitude: float | None
    longitude: float | None
    reported_at: datetime
    animal_group: AnimalGroup = AnimalGroup.UNKNOWN
    animal_count: int = 1
    #: The incident this report was linked to as a duplicate, if any.
    duplicate_of: str | None = None
    #: Whether someone is handling it now (see
    #: `duplicates.ACTIVE_DUPLICATE_TARGET_STATUSES`). Ended cases and
    #: unfinished intakes do not start or extend an event. A linked duplicate
    #: is cancelled, so it is never active itself; it counts through the
    #: incident it is linked to.
    is_active: bool = True


@dataclass
class _Scene:
    """An active incident plus the duplicate reports linked to it."""

    report: StrandingReport
    animal_count: int
    report_ids: list[str]


def find_mass_strandings(reports: list[StrandingReport]) -> dict[str, MassStranding]:
    """Every mass stranding among `reports`, keyed by incident id.

    Each incident in an event maps to the same `MassStranding`, and so does
    each duplicate linked to one of them, so a caller can look up any incident
    it is showing. An incident that is not part of one is absent.

    Pass every open incident and the duplicates linked to them. Passing only
    the incidents near one point gives the right answer for that point as long
    as the whole event is inside the area passed.
    """
    config = load_scoring_config()["mass_stranding"]
    groups = {AnimalGroup(name) for name in config["animal_groups"]}

    scenes = _build_scenes(reports, groups)
    events: dict[str, MassStranding] = {}

    for members in _join_nearby(scenes, config["distance_km"], config["time_hours"]):
        total = sum(scene.animal_count for scene in members)
        if total < config["min_animals"]:
            continue

        members.sort(key=lambda scene: scene.report.reported_at)
        report_count = sum(len(scene.report_ids) for scene in members)
        event = MassStranding(
            animal_count=total,
            animal_group=members[0].report.animal_group,
            incident_ids=[scene.report.incident_id for scene in members],
            report_count=report_count,
            reason=_describe(
                total, members[0].report.animal_group, len(members), report_count, config
            ),
        )
        for scene in members:
            for incident_id in scene.report_ids:
                events[incident_id] = event

    return events


def _build_scenes(reports: list[StrandingReport], groups: set[AnimalGroup]) -> list[_Scene]:
    """Fold each linked duplicate into the incident it was linked to."""
    scenes: dict[str, _Scene] = {}
    for report in reports:
        if (
            report.duplicate_of is None
            and report.is_active
            and report.animal_group in groups
            and report.latitude is not None
            and report.longitude is not None
        ):
            scenes[report.incident_id] = _Scene(
                report=report,
                animal_count=max(1, report.animal_count),
                report_ids=[report.incident_id],
            )

    for report in reports:
        scene = scenes.get(report.duplicate_of) if report.duplicate_of else None
        if scene is None:
            continue
        # The largest count, not the sum: these reporters are looking at the
        # same animals. The duplicate's own group is not checked -- it was
        # linked because it is the same scene, and a blurrier photo of it
        # being less sure what the animals are does not make them fewer.
        scene.animal_count = max(scene.animal_count, report.animal_count)
        scene.report_ids.append(report.incident_id)

    return list(scenes.values())


def _join_nearby(scenes: list[_Scene], max_km: float, max_hours: float) -> list[list[_Scene]]:
    """Group scenes into events: same animal group, close in place AND time."""
    unvisited = list(range(len(scenes)))
    events: list[list[_Scene]] = []

    while unvisited:
        frontier = [unvisited.pop()]
        event = []
        while frontier:
            current = frontier.pop()
            event.append(scenes[current])
            near = [
                i for i in unvisited if _is_near(scenes[current], scenes[i], max_km, max_hours)
            ]
            for i in near:
                unvisited.remove(i)
            frontier.extend(near)
        events.append(event)

    return events


def _is_near(a: _Scene, b: _Scene, max_km: float, max_hours: float) -> bool:
    if a.report.animal_group != b.report.animal_group:
        return False
    hours = abs((a.report.reported_at - b.report.reported_at).total_seconds()) / 3600.0
    if hours > max_hours:
        return False
    distance = haversine_km(
        a.report.latitude, a.report.longitude, b.report.latitude, b.report.longitude
    )
    return distance <= max_km


def _describe(
    total: int, group: AnimalGroup, incidents: int, reports: int, config: dict
) -> str:
    animals = _GROUP_NAMES.get(group, "animals")
    if incidents == 1:
        source = "one report" if reports == 1 else f"{reports} reports of one incident"
        text = f"At least {total} {animals} here, from {source}."
    else:
        text = (
            f"At least {total} {animals} across {incidents} incidents "
            f"({reports} reports) within {config['distance_km']:g} km and "
            f"{config['time_hours']:g} hours of each other."
        )
    if total == 2:
        # NOAA excludes a cow-calf pair. Nothing here can tell, so say so
        # rather than claim more than is known.
        text += " If these are a mother and calf, it is not a mass stranding."
    return text
