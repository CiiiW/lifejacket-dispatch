#!/usr/bin/env python3
"""Create demo incidents from a folder of photos plus a CSV.

Runs each row through the **real** intake API -- the same endpoints the
reporter app calls -- so the resulting incidents have genuine agent
identifications, severity scores, reports, and guardrail verdicts. Nothing is
written straight to the database, because a hand-faked report is exactly the
thing a demo must not show.

    demo/
      incidents.csv
      harbor_seal_pup.jpg
      entangled_sea_lion.jpg

`incidents.csv` columns (each accepts a few aliases, since this data usually
arrives as an export from somewhere else -- the resolved mapping is printed on
every run):

    photo           required  filename inside the demo folder
                              aliases: filename, file, image
    latitude        required  decimal degrees. aliases: lat
    longitude       required  decimal degrees. aliases: lon, lng, long
    condition       optional  one sentence on what the reporter sees; this is
                              what the assessment agent's questions get
                              answered with, and it is the difference between
                              varied demo data and five identical reports
                              aliases: notes, description, observation, outcome
    species         optional  GROUND TRUTH, not an override -- the agent still
                              identifies from the photo. Used to score the
                              agent and, for a few rows, to close the incident
                              with a responder log entry. A common name
                              compares better than a scientific one, so
                              `animal`/`common_name` win over `species`
    outcome         optional  rescued | released | deceased | not_found |
                              no_action_needed. Only read when the value is
                              actually one of those -- an `outcome` column
                              full of prose is treated as `condition` instead,
                              and the real outcome is inferred from it
    reporter_phone  optional  shows the console's "Call reporter" button.
                              Missing values are filled with reserved 555-01xx
                              fictional numbers unless --no-fake-phones

Usage:

    python scripts/seed_demo_incidents.py --dry-run     # validate, no API calls
    python scripts/seed_demo_incidents.py --limit 2     # try two rows first
    python scripts/seed_demo_incidents.py               # everything

Each row costs roughly 6-12 live model calls, so start with --limit.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Reports closer together than this in space and time are treated as the same
#: animal by `services/duplicates.py`, marked `cancelled`, and dropped from the
#: responder map. Read from the same config the backend uses so the two cannot
#: drift apart.
SCORING_CONFIG = REPO_ROOT / "config" / "scoring.json"

#: Questions about these topics get answered from the row's `condition` text.
#: Anything else is an identification question about visible anatomy, which the
#: agent's own tap-able options answer better than free text would.
CONDITION_TOPICS = (
    "injur", "wound", "blood", "bleed", "cut", "breath", "responsive",
    "move", "moving", "behav", "alert", "entangl", "net", "rope", "line",
    "debris", "hook", "tide", "water", "wave", "crowd", "dog", "people",
    "distress", "sick", "thin", "eye", "discharge", "pup", "mother", "alone",
)

#: Hard stop per incident. The agents may ask five identification and five
#: assessment questions; this leaves room for retakes without looping forever.
MAX_TURNS = 16

#: Accepted spellings for each field. First match in the CSV header wins, so
#: the order matters: a common name ("California sea lion") scores against the
#: agent's answer far better than a scientific one ("Zalophus californianus").
ALIASES: dict[str, tuple[str, ...]] = {
    "photo": ("photo", "filename", "file", "image"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "lng", "long"),
    "species": ("animal", "common_name", "species", "scientific_name"),
    "condition": ("condition", "notes", "description", "observation", "outcome"),
    "outcome": ("outcome",),
    "reporter_phone": ("reporter_phone", "phone"),
}

#: What the responder log accepts. A column called `outcome` holding anything
#: else is prose about the animal, not an outcome, and is read as `condition`.
VALID_OUTCOMES = {"rescued", "released", "deceased", "not_found", "no_action_needed"}

#: Phrases that mean the animal was already dead when found. Worth inferring:
#: logging a carcass as "rescued" would be wrong, and obviously so in a demo.
DECEASED_HINTS = (
    "dead", "deceased", "carcass", "not breathing", "no longer breathing",
    "decomposing", "remains",
)

#: 555-0100 through 555-0199 are reserved for fiction, so a made-up number
#: cannot ring a real person. Area codes are coastal US ones for plausibility.
FAKE_AREA_CODES = ("831", "805", "415", "707", "619", "207")

#: British/American spellings of the same animal. Without these, "Harbour
#: seal" and "Harbor seal" score as a miss, which blames the agent for the
#: spelling in the CSV.
SPELLING_VARIANTS = (
    ("harbour", "harbor"),
    ("grey", "gray"),
    ("colour", "color"),
)


def same_species(agent: str | None, truth: str) -> bool:
    """Whether the agent's answer and the ground truth name the same animal.

    Deliberately loose: the agent may answer at genus or family level
    ("Eared seals") where the truth is a species, and either side may use
    British spelling. Close enough for a demo scoreboard, not a substitute for
    the real evaluation harness in `notebooks/02_agent_evaluation.ipynb`.
    """

    def normalise(value: str) -> str:
        text = " ".join(value.strip().lower().split())
        for british, american in SPELLING_VARIANTS:
            text = text.replace(british, american)
        return text

    if not agent or not truth:
        return False
    left, right = normalise(agent), normalise(truth)
    return bool(left) and bool(right) and (left in right or right in left)


@dataclass
class Row:
    photo: Path
    latitude: float
    longitude: float
    condition: str = ""
    species: str = ""
    outcome: str = "rescued"
    reporter_phone: str = ""
    line_number: int = 0


@dataclass
class Result:
    row: Row
    incident_id: str
    complete: bool
    agent_species: str | None = None
    severity: str | None = None
    headline: str | None = None
    questions: list[str] = field(default_factory=list)
    logged: bool = False
    error: str | None = None


def duplicate_distance_km() -> float:
    with SCORING_CONFIG.open() as fh:
        return float(json.load(fh)["duplicate_matching"]["distance_km"])


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    """Map each field this script needs onto a column actually in the CSV."""
    available = {name.strip().lower(): name for name in fieldnames}
    mapping: dict[str, str] = {}
    for field_name, candidates in ALIASES.items():
        for candidate in candidates:
            if candidate in available:
                mapping[field_name] = available[candidate]
                break
    return mapping


def infer_outcome(raw_outcome: str, condition: str) -> str:
    """The logged outcome: taken from the CSV if it is one, else inferred."""
    if raw_outcome.strip().lower().replace(" ", "_") in VALID_OUTCOMES:
        return raw_outcome.strip().lower().replace(" ", "_")
    haystack = f"{raw_outcome} {condition}".lower()
    if any(hint in haystack for hint in DECEASED_HINTS):
        return "deceased"
    return "rescued"


def fake_phone(seed: str) -> str:
    """A reserved-for-fiction number, stable for a given photo name."""
    generator = random.Random(seed)
    return (
        f"+1{generator.choice(FAKE_AREA_CODES)}555"
        f"01{generator.randint(0, 99):02d}"
    )


def load_rows(csv_path: Path, photo_dir: Path, fake_phones: bool = True) -> list[Row]:
    """Parse and validate the CSV, raising on anything that would waste API calls."""
    if not csv_path.exists():
        raise SystemExit(
            f"No CSV at {csv_path}.\n\n"
            "Create it with at least these columns:\n"
            "  photo,latitude,longitude,condition,species\n"
            "and put the photos it names in the same folder."
        )

    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        columns = resolve_columns(fieldnames)

        missing = {"photo", "latitude", "longitude"} - columns.keys()
        if missing:
            raise SystemExit(
                f"{csv_path} has no column for: {', '.join(sorted(missing))}.\n"
                f"Found columns: {', '.join(fieldnames)}\n"
                "Accepted names per field:\n  "
                + "\n  ".join(f"{k}: {', '.join(v)}" for k, v in ALIASES.items())
            )

        # An `outcome` column doing duty as `condition` cannot also be the
        # outcome, so report what was actually used.
        print("column mapping:")
        for field_name in ("photo", "latitude", "longitude", "species", "condition"):
            source = columns.get(field_name)
            print(f"  {field_name:<14} <- {source if source else '(absent)'}")

        rows: list[Row] = []
        problems: list[str] = []

        def cell(raw: dict[str, str], field_name: str) -> str:
            source = columns.get(field_name)
            return (raw.get(source) or "").strip() if source else ""

        for offset, raw in enumerate(reader, start=2):
            name = cell(raw, "photo")
            if not name:
                problems.append(f"line {offset}: empty photo filename")
                continue

            photo = photo_dir / name
            if not photo.exists():
                problems.append(f"line {offset}: no such photo {photo}")
                continue

            try:
                latitude = float(cell(raw, "latitude"))
                longitude = float(cell(raw, "longitude"))
            except ValueError:
                problems.append(f"line {offset}: latitude/longitude must be decimal degrees")
                continue

            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                problems.append(f"line {offset}: latitude/longitude out of range")
                continue

            condition = cell(raw, "condition")
            phone = cell(raw, "reporter_phone")
            rows.append(
                Row(
                    photo=photo,
                    latitude=latitude,
                    longitude=longitude,
                    condition=condition,
                    species=cell(raw, "species"),
                    outcome=infer_outcome(cell(raw, "outcome"), condition),
                    reporter_phone=phone or (fake_phone(name) if fake_phones else ""),
                    line_number=offset,
                )
            )

    if problems:
        raise SystemExit("Problems in " + str(csv_path) + ":\n  " + "\n  ".join(problems))
    if not rows:
        raise SystemExit(f"{csv_path} has no usable rows.")

    check_spacing(rows)
    return rows


def check_spacing(rows: list[Row]) -> None:
    """Refuse rows that duplicate detection would silently merge and hide."""
    limit = duplicate_distance_km()
    clashes = [
        f"lines {a.line_number} and {b.line_number} are "
        f"{haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) * 1000:.0f} m apart"
        for i, a in enumerate(rows)
        for b in rows[i + 1 :]
        if haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) < limit
    ]
    if clashes:
        raise SystemExit(
            f"These rows are within {limit:g} km of each other, so the backend would "
            "treat the later ones as duplicate reports of the same animal, mark them "
            "'cancelled', and hide them from the responder console:\n  "
            + "\n  ".join(clashes)
            + "\n\nMove them further apart."
        )


def pick_answer(question: str, options: list[str], condition: str) -> str:
    """Answer one agent question as the reporter would.

    Identification questions ("can you see ear flaps?") are answered with the
    agent's own tap-able options, which is what a reporter on a phone would
    press. Condition questions are answered from the row's `condition` text,
    since no option list can describe a specific injury.
    """
    usable = [o for o in options if o.strip().lower() not in {"not sure", "unsure", "unknown"}]
    asks_about_condition = any(topic in question.lower() for topic in CONDITION_TOPICS)

    if asks_about_condition and condition:
        return condition
    if usable:
        return usable[0]
    if condition:
        return condition
    return "Not sure."


class Seeder:
    def __init__(self, api: str, responder_id: str) -> None:
        self.api = api.rstrip("/")
        self.responder_id = responder_id

    def post(self, path: str, **kwargs) -> dict:
        response = requests.post(f"{self.api}{path}", timeout=300, **kwargs)
        response.raise_for_status()
        return response.json()

    def seed(self, row: Row) -> Result:
        turn = self.post(
            "/intake/start",
            json={"reporter_phone": row.reporter_phone or None},
        )
        incident_id = turn["incident_id"]
        result = Result(row=row, incident_id=incident_id, complete=False)

        turn = self.upload(incident_id, row)
        turn = self.post(
            f"/intake/{incident_id}/location",
            json={
                "latitude": row.latitude,
                "longitude": row.longitude,
                "accuracy_meters": 10.0,
            },
        )

        retaken = False
        for _ in range(MAX_TURNS):
            if turn.get("complete"):
                break

            if turn.get("action") == "request_better_photo":
                # Only one photo exists per row, so offer it once more and then
                # say plainly that it is the best available.
                if not retaken:
                    retaken = True
                    turn = self.upload(incident_id, row)
                else:
                    turn = self.reply(
                        incident_id, "That is the clearest photo I can get from here."
                    )
                continue

            if not turn.get("awaiting_reply"):
                break

            question = turn.get("message") or ""
            answer = pick_answer(question, turn.get("options") or [], row.condition)
            result.questions.append(f"Q: {question.strip()[:70]} -> A: {answer[:50]}")
            turn = self.reply(incident_id, answer)

        result.complete = bool(turn.get("complete"))
        result.agent_species = turn.get("identified_as")
        result.severity = turn.get("severity_level")
        result.headline = turn.get("report_headline")
        return result

    def upload(self, incident_id: str, row: Row) -> dict:
        with row.photo.open("rb") as fh:
            return self.post(
                f"/intake/{incident_id}/photo",
                files={"file": (row.photo.name, fh, "image/jpeg")},
            )

    def reply(self, incident_id: str, text: str) -> dict:
        return self.post(f"/intake/{incident_id}/reply", json={"text": text})

    def log_ground_truth(self, result: Result) -> None:
        """Close an incident with a responder log entry carrying the true species.

        This is the only ground truth the system ever receives about whether
        the identification agent was right. It also sets the incident to
        `resolved`, which is why only a few rows get it -- a resolved incident
        leaves the console's open list.
        """
        self.post(
            f"/incidents/{result.incident_id}/log",
            json={
                "responder_id": self.responder_id,
                "confirmed_species": result.row.species,
                "outcome": result.row.outcome,
                "actions_taken": "Demo seed: outcome recorded without a real response.",
                "notes": f"Seeded from {result.row.photo.name}.",
                "report_was_accurate": same_species(
                    result.agent_species, result.row.species
                ),
            },
        )
        result.logged = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dir",
        type=Path,
        default=REPO_ROOT / "demo",
        help="folder holding the photos and incidents.csv (default: demo/)",
    )
    parser.add_argument("--csv", type=Path, default=None, help="default: <dir>/incidents.csv")
    parser.add_argument("--api", default="http://localhost:8000", help="running backend")
    parser.add_argument("--limit", type=int, default=None, help="seed only the first N rows")
    parser.add_argument(
        "--log-ground-truth",
        type=int,
        default=2,
        metavar="N",
        help="close the first N seeded incidents with a responder log entry "
        "carrying the true species, so the demo includes resolved incidents "
        "as well as open ones (default: 2; use 0 to keep everything open)",
    )
    parser.add_argument(
        "--responder-id",
        default="org_the_marine_mammal_center_monterey_bay_operat",
        help="who the log entries are attributed to",
    )
    parser.add_argument(
        "--no-fake-phones",
        dest="fake_phones",
        action="store_false",
        help="leave reporter_phone empty instead of filling it with a "
        "reserved 555-01xx fictional number (which makes the console's "
        "'Call reporter' button appear)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the CSV, photos, and spacing without calling the API",
    )
    args = parser.parse_args()

    csv_path = args.csv or (args.dir / "incidents.csv")
    rows = load_rows(csv_path, args.dir, fake_phones=args.fake_phones)
    if args.limit is not None:
        rows = rows[: args.limit]

    without_condition = [r.line_number for r in rows if not r.condition]
    if without_condition:
        print(
            f"note: {len(without_condition)} row(s) have no `condition` text "
            f"(lines {without_condition}). Their assessment questions will be "
            "answered 'Not sure', which flattens severity and makes the reports "
            "look alike.\n"
        )

    print(f"{len(rows)} row(s) validated from {csv_path}")
    if args.dry_run:
        for row in rows:
            print(
                f"  line {row.line_number}: {row.photo.name} at "
                f"({row.latitude}, {row.longitude}) outcome={row.outcome}"
                + (f" phone={row.reporter_phone}" if row.reporter_phone else "")
                + (f"\n    truth: {row.species}" if row.species else "")
                + (f"\n    condition: {row.condition[:80]}" if row.condition else "")
            )
        print("\nDry run: no incidents created.")
        return 0

    try:
        requests.get(f"{args.api.rstrip('/')}/incidents", timeout=10).raise_for_status()
    except requests.RequestException as error:
        raise SystemExit(
            f"Cannot reach the backend at {args.api} ({error}).\nStart it with `make run`."
        ) from error

    seeder = Seeder(args.api, args.responder_id)
    results: list[Result] = []

    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] {row.photo.name} ... ", end="", flush=True)
        try:
            result = seeder.seed(row)
        except requests.RequestException as error:
            print(f"failed: {error}")
            results.append(
                Result(row=row, incident_id="-", complete=False, error=str(error))
            )
            continue

        print(
            f"{result.incident_id} "
            f"{'complete' if result.complete else 'INCOMPLETE'}, "
            f"agent said {result.agent_species or '?'}, "
            f"severity {result.severity or '?'}, "
            f"{len(result.questions)} question(s)"
        )
        results.append(result)

    to_log = [r for r in results if r.complete and r.row.species][: args.log_ground_truth]
    for result in to_log:
        try:
            seeder.log_ground_truth(result)
            print(f"logged ground truth and closed {result.incident_id}")
        except requests.RequestException as error:
            print(f"could not log {result.incident_id}: {error}")

    report(results)
    return 0 if all(r.complete for r in results) else 1


def report(results: list[Result]) -> None:
    print("\n--- agent identification vs ground truth ---")
    scored = [r for r in results if r.row.species]
    if not scored:
        print("(no `species` column values, so nothing to score)")
    for result in scored:
        agent = (result.agent_species or "?").strip()
        hit = same_species(result.agent_species, result.row.species)
        print(
            f"  {'MATCH ' if hit else 'MISS  '} agent: {agent:<28} "
            f"truth: {result.row.species.strip()}"
        )
    if scored:
        hits = sum(1 for r in scored if same_species(r.agent_species, r.row.species))
        print(f"  {hits}/{len(scored)} matched (loose name comparison)")

    created = [r for r in results if r.complete]
    closed = [r for r in results if r.logged]
    print(
        f"\n{len(created)}/{len(results)} incident(s) completed; "
        f"{len(closed)} closed with ground truth, "
        f"{len(created) - len(closed)} left open on the console."
    )
    for result in [r for r in results if not r.complete]:
        why = result.error or "intake did not finish"
        print(f"  incomplete: {result.row.photo.name} ({why})")


if __name__ == "__main__":
    sys.exit(main())
