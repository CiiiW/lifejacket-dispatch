"""Collect public iNaturalist condition candidates; never infer medical labels.

Run from the repository root:
  python research/public_condition_pilot/collect.py --download --limit 40

Metadata/review templates are versioned; original image bytes stay in photos/.
Only CC0 and CC BY images are selected for this initial pilot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import time
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests
from lifejacket.models.schemas import AnimalGroup
from PIL import Image

HERE = Path(__file__).resolve().parent
SEEDS = HERE.parent / "identification_eval" / "manifest.csv"
API = "https://api.inaturalist.org/v1"
PROJECT = "wildlife-diseases-morbidity-and-mortality"
LICENSES = {"cc0", "cc-by"}
CUES = {
    "entanglement_mention": r"\b(entangl\w*|fishing line|fishing net)\b",
    "wound_mention": r"\b(wound\w*|lacerat\w*|open sore\w*)\b",
    "bleeding_mention": r"\b(bleed\w*|blood\w*)\b",
    "injury_mention": r"\b(injur\w*|fractur\w*|broken\s+(?:wing|leg|flipper))\b",
    "oiling_mention": r"\b(oiled|oil spill|oil-covered)\b",
    "illness_mention": r"\b(diseas\w*|infect\w*|conjunctivitis|mange)\b",
}
CONDITION_FIELD = re.compile(
    r"injur|diseas|health|alive|dead|mort|entangl|wound|blood|bleed|oil|deform|cause|condition",
    re.I,
)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def clean_text(value):
    parser = PlainText()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())[:2000]


def photo_url(photo):
    url = photo.get("url") or ""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "inaturalist-open-data.s3.amazonaws.com",
        "static.inaturalist.org",
    }:
        return None
    return re.sub(r"/square\.", "/large.", url)


def candidate(obs, sources, seed_groups, taxon_groups):
    """Community text is evidence to review, never a positive/negative label."""
    photo = next(
        (
            p
            for p in obs.get("photos", [])
            if p.get("license_code") in LICENSES and photo_url(p)
        ),
        None,
    )
    if photo is None:
        return None
    text_allowed = obs.get("license_code") in LICENSES
    evidence = []
    if text_allowed:
        description = clean_text(obs.get("description"))
        if description:
            evidence.append({"kind": "observer_description", "text": description})
        for field in obs.get("ofvs", []):
            name, value = clean_text(field.get("name")), clean_text(field.get("value"))
            if name and value and CONDITION_FIELD.search(name):
                evidence.append(
                    {
                        "kind": "community_field",
                        "field_id": field.get("field_id"),
                        "name": name,
                        "text": value,
                    }
                )
        if obs.get("tags"):
            evidence.append({"kind": "observer_tags", "text": ", ".join(obs["tags"])[:2000]})
    combined = " ".join(f"{item.get('name', '')} {item['text']}" for item in evidence)
    mentions = [name for name, pattern in CUES.items() if re.search(pattern, combined, re.I)]
    # These are text mentions, including negations/speculation, not findings.
    taxon = obs.get("taxon") or {}
    group = seed_groups.get(obs["id"], taxon_groups.get(taxon.get("id"), "unknown"))
    AnimalGroup(group)  # Reject taxonomy drift instead of inventing a new group.
    annotations = [
        {
            "attribute_id": a.get("controlled_attribute_id"),
            "value_id": a.get("controlled_value_id"),
        }
        for a in obs.get("annotations", [])
        if a.get("controlled_attribute_id") == 17
    ]
    observer = obs.get("user") or {}
    observer_credit = observer.get("login") or observer.get("id")
    return {
        "case_id": f"inat_{obs['id']}_{photo['id']}",
        "observation_id": obs["id"],
        "observation_url": f"https://www.inaturalist.org/observations/{obs['id']}",
        "observed_on": obs.get("observed_on"),
        "observer_id": (obs.get("user") or {}).get("id"),
        "taxon": {
            "id": taxon.get("id"),
            "scientific_name": taxon.get("name"),
            "common_name": taxon.get("preferred_common_name"),
        },
        "quality_grade": obs.get("quality_grade"),
        "animal_group_hint": group,
        "group_hint_basis": "identification evaluation taxon mapping"
        if group != "unknown"
        else "unresolved",
        "prior_identification_eval": obs["id"] in seed_groups,
        "sources": sources,
        "observation_license": obs.get("license_code"),
        "observation_attribution": f"iNaturalist observer {observer_credit}",
        "condition_text_omitted_for_license": not text_allowed,
        "community_evidence": evidence,
        "community_alive_dead_annotations": annotations,
        "condition_mentions": mentions,
        "label_status": "unverified_candidate",
        "expert_reviewed": False,
        "photo": {
            "id": photo["id"],
            "url": photo_url(photo),
            "license": photo["license_code"],
            "attribution": photo.get("attribution"),
            "download_status": "not_requested",
        },
        "review": {
            "animal_group": None,
            "viewpoint": "unknown",
            "visible_wound": None,
            "bleeding": None,
            "entanglement": None,
            "swelling": None,
            "abnormal_posture": None,
            "emaciated": None,
            "condition_unknown": True,
            "reviewer": None,
            "reviewer_qualification": None,
            "reviewed_at": None,
            "notes": None,
            "split": "unassigned_development_candidate",
        },
    }


def balanced(rows, limit):
    buckets = defaultdict(deque)
    for row in sorted(
        rows, key=lambda r: (not bool(r["condition_mentions"]), r["observation_id"])
    ):
        buckets[row["animal_group_hint"]].append(row)
    picked, observers = [], Counter()
    while buckets and len(picked) < limit:
        for group in list(buckets):
            bucket = buckets[group]
            while bucket:
                row = bucket.popleft()
                observer = row["observer_id"] or row["observation_id"]
                if observers[observer] < 2:
                    picked.append(row)
                    observers[observer] += 1
                    break
            if not bucket:
                del buckets[group]
            if len(picked) == limit:
                break
    return picked


class PublicClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "LifeJacketDispatch-public-condition-research/1.0"

    def observations(self, **params):
        for attempt in range(3):
            time.sleep(1.1)
            response = self.session.get(f"{API}/observations", params=params, timeout=30)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.json()["results"]
        raise RuntimeError("iNaturalist unavailable after bounded retries")

    def download(self, row, output):
        photo = row["photo"]
        if photo.get("license") not in LICENSES or photo_url(photo) != photo["url"]:
            raise ValueError("Photo URL or license is outside this pilot's collection policy")
        response = self.session.get(photo["url"], timeout=30, stream=True)
        response.raise_for_status()
        data = bytearray()
        for block in response.iter_content(65536):
            data.extend(block)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("Photo exceeds pilot limit of 8 MiB")
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("Photo exceeds pilot limit of 20 MP")
            extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(image.format)
            if not extension:
                raise ValueError("Unsupported photo format")
            width, height = image.size
            image.verify()
        path = output / "photos" / f"{photo['id']}.{extension}"
        checksum = hashlib.sha256(data).hexdigest()
        if photo.get("sha256") and checksum != photo["sha256"]:
            raise ValueError("Remote photo differs from the saved collection snapshot")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)  # Original bytes, without conversion or cropping.
        photo.update(
            download_status="saved",
            file=str(path.relative_to(output)),
            sha256=checksum,
            bytes=len(data),
            width=width,
            height=height,
        )


def collect(output, limit=40, download=False):
    output.mkdir(parents=True, exist_ok=True)
    if (output / "candidates.jsonl").exists():
        raise ValueError(
            "Collection already exists; choose a new output directory to preserve reviews"
        )
    seeds = list(csv.DictReader(SEEDS.open(encoding="utf-8")))
    seed_groups = {int(r["observation_id"]): r["animal_group"] for r in seeds}
    client = PublicClient()
    observations, sources, queries, taxon_groups = {}, defaultdict(list), [], {}

    def fetch(reason, params):
        queries.append({"reason": reason, "params": params})
        results = client.observations(**params)
        print(f"Retrieved {len(results)} observations: {reason}", flush=True)
        for obs in results:
            observations[obs["id"]] = obs
            sources[obs["id"]].append(reason)
        return results

    ids = list(seed_groups)
    for start in range(0, len(ids), 50):
        results = fetch(
            "existing_identification_eval",
            {
                "id": ",".join(map(str, ids[start : start + 50])),
                "per_page": 50,
            },
        )
        for obs in results:
            if obs["id"] not in seed_groups:
                raise ValueError("Seed query returned an unexpected observation ID")
            taxon = obs.get("taxon") or {}
            if taxon.get("id") and obs["id"] in seed_groups:
                taxon_groups[taxon["id"]] = seed_groups[obs["id"]]
    if not taxon_groups:
        raise ValueError("No seed taxa retrieved; refusing an unrestricted condition search")
    base = {
        "photos": "true",
        "photo_license": ",".join(sorted(LICENSES)),
        "per_page": 25,
        "order_by": "id",
        "order": "desc",
    }
    fetch(f"project:{PROJECT}", {**base, "project_id": PROJECT})
    for term in ("injured", "entangled", "wound", "oiled"):
        fetch(
            f"text_search:{term}",
            {**base, "taxon_id": ",".join(map(str, sorted(taxon_groups))), "q": term},
        )
    rows = [
        candidate(obs, sources[oid], seed_groups, taxon_groups)
        for oid, obs in observations.items()
    ]
    rows = balanced([r for r in rows if r], limit)
    hashes = {}
    for index, row in enumerate(rows, start=1):
        if download:
            try:
                client.download(row, output)
            except (requests.RequestException, OSError, ValueError) as exc:
                row["photo"].update(download_status="failed", error=type(exc).__name__)
        checksum = row["photo"].get("sha256")
        if checksum:
            row["duplicate_photo_of"] = hashes.get(checksum)
            hashes.setdefault(checksum, row["case_id"])
        # Checkpoint each selected record so partial media failures lose no metadata.
        with (output / "candidates.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"Saved candidate {index}/{len(rows)}: {row['photo']['download_status']}",
            flush=True,
        )
    summary = {
        "retrieved_at": datetime.now(UTC).isoformat(),
        "queries": queries,
        "candidate_count": len(rows),
        "expert_reviewed_count": 0,
        "group_hints": dict(Counter(r["animal_group_hint"] for r in rows)),
        "condition_mentions": dict(Counter(c for r in rows for c in r["condition_mentions"])),
        "downloads": dict(Counter(r["photo"]["download_status"] for r in rows)),
        "missing_named_groups": [
            g.value
            for g in AnimalGroup
            if g is not AnimalGroup.UNKNOWN
            and not any(r["animal_group_hint"] == g.value for r in rows)
        ],
        "limitations": [
            "Community reports and text mentions are unverified leads, including negations.",
            "Alive does not mean healthy; dead does not identify injury or cause of death.",
            "No expert-reviewed labels, no model training, no accuracy claim.",
            "Viewpoint is unknown until reviewed; this is not an aerial evaluation set.",
            "NOAA evaluation cases must remain held out from development and training.",
        ],
    }
    (output / "collection.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in {"queries", "limitations"}}, indent=2
        )
    )


def fetch_existing(output):
    """Recreate original media from the saved manifest without changing reviews."""
    rows = [
        json.loads(line) for line in (output / "candidates.jsonl").read_text().splitlines()
    ]
    client, counts = PublicClient(), Counter()
    for row in rows:
        photo = row["photo"]
        path = output / photo["file"] if photo.get("file") else None
        if (
            path
            and path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == photo.get("sha256")
        ):
            counts["already_present"] += 1
            continue
        try:
            client.download(row, output)
            counts["downloaded"] += 1
        except (requests.RequestException, OSError, ValueError) as exc:
            counts["failed"] += 1
            print(f"Photo {photo['id']}: {type(exc).__name__}", flush=True)
        time.sleep(0.3)
    print(json.dumps(dict(counts), indent=2))
    if counts["failed"]:
        raise RuntimeError(
            "Some original photos could not be restored; do not substitute new photos"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=HERE / "pilot_v1")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--fetch-existing", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    if args.fetch_existing:
        fetch_existing(args.output)
    else:
        collect(args.output, args.limit, args.download)
