"""Build the identification test photos from iNaturalist.

    python download_photos.py build    # pick observations, write manifest.csv, download photos
    python download_photos.py fetch    # download any photos in manifest.csv that are missing

`build` refuses to overwrite an existing manifest.csv (it may hold hand-corrected
labels); pass --force to start over. `fetch` is how a teammate recreates photos/
from a cloned repo: photos are not committed, manifest.csv is.

Only research-grade observations (several identifiers agree on the species) with
a Creative Commons photo licence are used; the licence and attribution travel
with every row. Domestic animals are never research grade on iNaturalist, so
those come from captive observations instead.
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import sys
import time
from pathlib import Path

import requests
from PIL import Image

HERE = Path(__file__).parent
MANIFEST = HERE / "manifest.csv"
PHOTOS = HERE / "photos"

API = "https://api.inaturalist.org/v1"
USER_AGENT = "LifeJacketDispatch/1.0 (xwang68@uchicago.edu)"
UNITED_STATES = 1  # iNaturalist place_id
CC_LICENCES = "cc0,cc-by,cc-by-nc,cc-by-sa,cc-by-nd,cc-by-nc-sa,cc-by-nc-nd"
LAS_VEGAS_BOX = {"swlat": 35.9, "swlng": -115.4, "nelat": 36.4, "nelng": -114.9}
SEED = 20261005
MAX_PER_OBSERVER = 3
POOL_SIZE = 60  # observations fetched per query before choosing

# (scientific name, animal_group, how many photos). Groups match AnimalGroup.
MARINE = [
    # Pinnipeds
    ("Zalophus californianus", "pinniped", 4),
    ("Eumetopias jubatus", "pinniped", 3),
    ("Phoca vitulina", "pinniped", 4),
    ("Mirounga angustirostris", "pinniped", 4),
    ("Callorhinus ursinus", "pinniped", 2),
    ("Arctocephalus townsendi", "pinniped", 2),
    ("Halichoerus grypus", "pinniped", 3),
    ("Neomonachus schauinslandi", "pinniped", 3),
    ("Phoca largha", "pinniped", 2),
    ("Odobenus rosmarus", "pinniped", 2),
    # Cetaceans
    ("Tursiops truncatus", "cetacean", 4),
    ("Delphinus delphis", "cetacean", 3),
    ("Aethalodelphis obliquidens", "cetacean", 2),  # Pacific white-sided dolphin
    ("Phocoena phocoena", "cetacean", 2),
    ("Eschrichtius robustus", "cetacean", 3),
    ("Megaptera novaeangliae", "cetacean", 3),
    ("Orcinus orca", "cetacean", 3),
    ("Balaenoptera acutorostrata", "cetacean", 2),
    ("Phocoenoides dalli", "cetacean", 2),
    ("Globicephala macrorhynchus", "cetacean", 2),
    ("Stenella longirostris", "cetacean", 2),
    ("Physeter macrocephalus", "cetacean", 1),
    ("Grampus griseus", "cetacean", 2),
    ("Delphinapterus leucas", "cetacean", 1),
    # Sea turtles
    ("Chelonia mydas", "sea_turtle", 4),
    ("Caretta caretta", "sea_turtle", 3),
    ("Dermochelys coriacea", "sea_turtle", 2),
    ("Lepidochelys kempii", "sea_turtle", 2),
    ("Lepidochelys olivacea", "sea_turtle", 1),
    # Seabirds
    ("Pelecanus occidentalis", "seabird", 3),
    ("Larus occidentalis", "seabird", 2),
    ("Uria aalge", "seabird", 2),
    ("Nannopterum auritum", "seabird", 2),
    ("Morus bassanus", "seabird", 2),
    ("Gavia immer", "seabird", 1),
    # Other marine
    ("Enhydra lutris", "other_marine", 3),
    ("Trichechus manatus", "other_marine", 3),
    ("Mola mola", "other_marine", 1),
    ("Physalia physalis", "other_marine", 2),
]

# Inland "trap" cases around Las Vegas: no ocean, so none of these should be
# identified as a marine animal.
INLAND = [
    ("Canis latrans", "terrestrial", 3, False),
    ("Gopherus agassizii", "terrestrial", 2, False),
    ("Buteo jamaicensis", "terrestrial", 2, False),
    ("Canis familiaris", "domestic_animal", 2, True),
    ("Felis catus", "domestic_animal", 1, True),
]

COLUMNS = [
    "case_id", "file", "species_common", "species_scientific", "genus", "family",
    "animal_group", "alive_or_dead", "latitude", "longitude",
    "place_guess", "observed_on", "coords_obscured", "observation_id",
    "observation_url", "photo_url", "photo_license", "photo_attribution",
]


def get(path: str, **params) -> dict:
    """GET from the iNaturalist API, politely (about one request a second)."""
    for attempt in range(4):
        time.sleep(1.1)
        response = requests.get(
            f"{API}{path}", params=params, headers={"User-Agent": USER_AGENT}, timeout=30
        )
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"iNaturalist kept failing for {path} {params}")


def resolve_taxon(scientific: str) -> dict | None:
    """Taxon record (id, names, family) for an exact scientific-name match."""
    results = get("/taxa", q=scientific, rank="species", per_page=5)["results"]
    match = next((t for t in results if t["name"].lower() == scientific.lower()), None)
    if match is None:
        return None
    detail = get(f"/taxa/{match['id']}")["results"][0]
    ancestors = detail.get("ancestors", [])
    family = next((a["name"] for a in ancestors if a["rank"] == "family"), "")
    return {
        "id": match["id"],
        "scientific": match["name"],
        "common": match.get("preferred_common_name") or match["name"],
        "family": family,
    }


def observations(taxon_id: int, **extra) -> list[dict]:
    """Observations of a taxon that have a usable, CC-licensed photo and a location."""
    params = {
        "taxon_id": taxon_id, "photos": "true", "geo": "true",
        "photo_license": CC_LICENCES, "per_page": POOL_SIZE, "order_by": "votes",
    }
    params.update(extra)
    found = get("/observations", **params)["results"]
    return [o for o in found if o.get("photos") and o.get("location")]


def alive_or_dead(obs: dict) -> str:
    values = {18: "alive", 19: "dead", 20: "cannot be determined"}
    for annotation in obs.get("annotations", []):
        if annotation.get("controlled_attribute_id") == 17:  # the "Alive or Dead" term
            return values.get(annotation.get("controlled_value_id"), "")
    return ""


def choose(pools: list[tuple[str, list[dict]]], count: int, rng: random.Random,
           observer_use: dict[str, int]) -> list[tuple[dict, str]]:
    """Take `count` observations, trying each pool in order (stranded/dead first).

    At most one photo per observer per species, and a few per observer overall,
    so one enthusiastic photographer does not dominate the set.
    """
    chosen: list[tuple[dict, str]] = []
    seen_obs, seen_users = set(), set()
    # About half stranded/dead, half ordinary, shared across both special pools.
    # An odd count rounds up or down at random so single-photo species vary.
    special_quota = count // 2 + (count % 2 and rng.random() < 0.5)
    special_taken = 0
    for note, pool in pools:
        pool = list(pool)
        rng.shuffle(pool)
        pool.sort(key=lambda o: bool(o.get("obscured")))  # prefer exact coordinates
        for obs in pool:
            if len(chosen) >= count:
                return chosen
            if note != "general" and special_taken >= special_quota:
                break
            user = obs["user"]["login"]
            if (obs["id"] in seen_obs or user in seen_users
                    or observer_use.get(user, 0) >= MAX_PER_OBSERVER):
                continue
            seen_obs.add(obs["id"])
            seen_users.add(user)
            observer_use[user] = observer_use.get(user, 0) + 1
            chosen.append((obs, note))
            if note != "general":
                special_taken += 1
    return chosen


def download(url: str, destination: Path) -> None:
    """Fetch a photo and store it as a JPEG (iNaturalist 'large' is at most 1024 px)."""
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    destination.parent.mkdir(exist_ok=True)
    image.save(destination, "JPEG", quality=90)


def build(force: bool) -> None:
    if MANIFEST.exists() and not force:
        sys.exit(f"{MANIFEST.name} already exists. Use --force to rebuild it from scratch.")
    rng = random.Random(SEED)
    observer_use: dict[str, int] = {}
    rows: list[dict] = []

    targets = [(s, g, n, None, False) for s, g, n in MARINE]
    targets += [(s, g, n, LAS_VEGAS_BOX, captive) for s, g, n, captive in INLAND]

    for scientific, group, count, box, captive in targets:
        taxon = resolve_taxon(scientific)
        if taxon is None:
            print(f"!! no exact taxon match for {scientific}; skipped")
            continue

        if captive:
            base = {"captive": "true", **box}
            pools = [("general", observations(taxon["id"], **base))]
        elif box:
            base = {"quality_grade": "research", **box}
            pools = [("general", observations(taxon["id"], **base))]
        else:
            base = {"quality_grade": "research", "place_id": UNITED_STATES}
            pools = [
                ("text match: stranded", observations(taxon["id"], q="stranded", **base)),
                ("annotation: dead", observations(
                    taxon["id"], term_id=17, term_value_id=19, **base)),
                ("general", observations(taxon["id"], **base)),
            ]

        picked = choose(pools, count, rng, observer_use)
        print(f"{scientific:<32} wanted {count}, got {len(picked)}")
        for index, (obs, _) in enumerate(picked, start=1):
            photo = obs["photos"][0]
            latitude, longitude = obs["location"].split(",")
            case_id = f"{scientific.lower().replace(' ', '_')}_{index:02d}"
            rows.append({
                "case_id": case_id,
                "file": f"{case_id}.jpg",
                "species_common": taxon["common"],
                "species_scientific": taxon["scientific"],
                "genus": taxon["scientific"].split()[0],
                "family": taxon["family"],
                "animal_group": group,
                "alive_or_dead": alive_or_dead(obs),
                "latitude": latitude,
                "longitude": longitude,
                "place_guess": obs.get("place_guess") or "",
                "observed_on": obs.get("observed_on") or "",
                "coords_obscured": bool(obs.get("obscured")),
                "observation_id": obs["id"],
                "observation_url": obs["uri"],
                "photo_url": photo["url"].replace("square", "large"),
                "photo_license": photo.get("license_code") or "",
                "photo_attribution": photo.get("attribution") or "",
            })

    with open(MANIFEST, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {MANIFEST.name}")
    fetch()


def fetch() -> None:
    with open(MANIFEST, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    missing = [r for r in rows if not (PHOTOS / r["file"]).exists()]
    print(f"{len(rows) - len(missing)} photos present, {len(missing)} to download")
    for row in missing:
        try:
            download(row["photo_url"], PHOTOS / row["file"])
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"!! {row['file']}: {exc}")
        time.sleep(0.3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["build", "fetch"])
    parser.add_argument("--force", action="store_true", help="rebuild an existing manifest")
    args = parser.parse_args()
    build(args.force) if args.command == "build" else fetch()
