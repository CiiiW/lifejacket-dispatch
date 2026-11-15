"""Turn a labelled COCO export into the split layout RF-DETR trains on.

    python dataset.py --coco labelled/_annotations.coco.json \
        --images labelled/images --out ~/aerial-data/seals

    # inspect the split without writing anything
    python dataset.py --coco ... --images ... --out ... --inspect

Produces what `rfdetr` expects:

    out/
      train/_annotations.coco.json  + images
      valid/_annotations.coco.json  + images
      test/_annotations.coco.json   + images

**Splits are assigned by capture session, never at random.** Consecutive
frames of one animal are near-identical; split them randomly and the same
animal lands in train and test, so the model has effectively seen the answers
and the reported score is fiction. A session is assigned by hashing its name,
so it lands in the same split on every machine, whatever order the files are
walked in.

The session name is taken from the image's parent directory, or from the
filename with a trailing frame number stripped. `--group-regex` overrides it.
Always check the groups `--inspect` prints before writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from dmd import DMD_CLASSES, RESULTS, write_coco  # noqa: E402

SPLITS = ("train", "valid", "test")


def session_of(file_name: str, regex: re.Pattern[str] | None) -> str:
    """Which capture session a frame belongs to."""
    path = Path(file_name)
    if regex is not None:
        hit = regex.search(path.name)
        if hit:
            return hit.group(1)
    parts = [p for p in path.parent.parts if p not in {".", "", "images", "frames"}]
    if parts:
        return "/".join(parts)
    stripped = re.sub(r"[-_]?\d+$", "", path.stem)
    return stripped or path.stem


def assign_splits(
    session_sizes: dict[str, int], train_pct: int, valid_pct: int
) -> dict[str, str]:
    """Assign whole sessions to splits, deterministically and proportionally.

    Hashing each session independently is the obvious approach and it is
    wrong at this scale: with six sessions and a 70% train share there is a
    0.7**6 chance -- about one in eight -- that every session lands in train
    and the other two splits come out empty. That is a coin flip you would
    lose regularly, because a labelling effort produces tens of sessions, not
    thousands.

    Instead: order sessions by a hash of their name (deterministic, content
    based, independent of how the files were walked), then cut that ordering
    at the requested fractions *of images*, so the volume of data lands where
    it was asked to. Sessions still never straddle a split.
    """
    if not session_sizes:
        return {}
    ordered = sorted(session_sizes, key=lambda s: hashlib.md5(s.encode()).hexdigest())
    total = sum(session_sizes.values())
    train_edge = total * train_pct / 100
    valid_edge = total * (train_pct + valid_pct) / 100

    assignment: dict[str, str] = {}
    seen = 0
    for session in ordered:
        size = session_sizes[session]
        midpoint = seen + size / 2
        if midpoint < train_edge:
            assignment[session] = "train"
        elif midpoint < valid_edge:
            assignment[session] = "valid"
        else:
            assignment[session] = "test"
        seen += size

    # With few sessions a split can still come out empty. Donate from the
    # largest split, taking its boundary session so the ordering stays sane.
    if len(ordered) >= len(SPLITS):
        for split in SPLITS:
            if any(v == split for v in assignment.values()):
                continue
            donor = max(SPLITS, key=lambda s: sum(1 for v in assignment.values() if v == s))
            members = [s for s in ordered if assignment[s] == donor]
            if len(members) > 1:
                assignment[members[-1] if split != "train" else members[0]] = split
    return assignment


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--coco", type=Path, required=True, help="labelled COCO export")
    parser.add_argument(
        "--images", type=Path, help="image directory (default: beside the COCO file)"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--train-pct", type=int, default=70)
    parser.add_argument("--valid-pct", type=int, default=15)
    parser.add_argument("--group-regex", help="override session detection; group 1 is the key")
    parser.add_argument("--inspect", action="store_true", help="report and stop")
    parser.add_argument("--copy", action="store_true", help="copy instead of symlink")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.train_pct + args.valid_pct >= 100:
        parser.error("--train-pct + --valid-pct must leave room for a test split")

    doc = json.loads(args.coco.read_text())
    images_root = args.images or args.coco.parent
    regex = re.compile(args.group_regex) if args.group_regex else None

    # Category ids from a labelling tool are arbitrary; match on name.
    index = {name.lower(): i for i, name in enumerate(DMD_CLASSES)}
    remap: dict[int, int] = {}
    for category in doc.get("categories", []):
        name = str(category["name"]).strip().lower()
        if name not in index:
            raise SystemExit(
                f"category {category['name']!r} is not one of {list(DMD_CLASSES)}. "
                "Rename it in the labelling export so every checkpoint here stays "
                "interchangeable."
            )
        remap[category["id"]] = index[name]

    by_image = defaultdict(list)
    for ann in doc.get("annotations", []):
        by_image[ann["image_id"]].append(ann)

    assigned: dict[str, list[dict]] = {s: [] for s in SPLITS}
    counts: dict[str, Counter] = {s: Counter() for s in SPLITS}
    empty = Counter()

    # Two passes: size every session first, because the assignment balances
    # by image volume and cannot be made one image at a time.
    by_session: dict[str, list[dict]] = defaultdict(list)
    for image in doc.get("images", []):
        by_session[session_of(image["file_name"], regex)].append(image)

    sessions = assign_splits(
        {name: len(group) for name, group in by_session.items()},
        args.train_pct,
        args.valid_pct,
    )
    for name, group in by_session.items():
        split = sessions[name]
        for image in group:
            assigned[split].append(image)
            boxes = by_image.get(image["id"], [])
            if not boxes:
                empty[split] += 1
            for ann in boxes:
                counts[split][DMD_CLASSES[remap[ann["category_id"]]]] += 1

    print("\n--- split ---")
    for split in SPLITS:
        per_class = " ".join(f"{k}={v}" for k, v in sorted(counts[split].items())) or "-"
        print(
            f"  {split:6s} {len(assigned[split]):5d} images  "
            f"{sum(counts[split].values()):6d} boxes   {per_class}"
        )
    print(f"\n  sessions: {len(sessions)}")
    for session in sorted(sessions)[:12]:
        print(f"    {sessions[session]:6s} {session}")
    if len(sessions) > 12:
        print(f"    ... and {len(sessions) - 12} more")
    print(f"  images with no boxes (kept as background): {dict(empty)}")

    # Assignment is by whole session, so a handful of sessions can leave a
    # split empty however the percentages are set. rfdetr needs train/ and
    # valid/ to be non-empty, and an empty test/ means nothing to report on.
    blank = [s for s in SPLITS if not assigned[s]]
    if blank:
        fatal = [s for s in blank if s in {"train", "valid"}]
        print(f"\n  {'ERROR' if fatal else 'WARNING'}: empty split(s): {blank}")
        print(
            f"  You have {len(sessions)} session(s), assigned whole. That cannot\n"
            "  reliably fill three splits. Options, best first:\n"
            "    - label more capture sessions (the real fix)\n"
            "    - --group-regex to split existing sessions finer, e.g. by\n"
            "      flight leg, as long as the pieces hold different animals\n"
            "    - --train-pct / --valid-pct to shift the hash boundaries"
        )
        if fatal and not args.inspect:
            raise SystemExit(
                f"\nrefusing to write: {fatal} would be empty and finetune.py needs both."
            )

    if args.inspect:
        print("\n--inspect: nothing written. Check the sessions above, then rerun.")
        return 0

    if args.out.exists() and not args.overwrite:
        raise SystemExit(f"{args.out} exists. Pass --overwrite.")
    if args.out.exists():
        shutil.rmtree(args.out)

    for split in SPLITS:
        target = args.out / split
        target.mkdir(parents=True)
        out_images, out_annotations = [], []
        next_ann = 1
        for new_id, image in enumerate(assigned[split], start=1):
            src = images_root / image["file_name"]
            if not src.exists():
                src = images_root / Path(image["file_name"]).name
            if not src.exists():
                print(f"  missing image {image['file_name']}, skipping")
                continue
            name = Path(image["file_name"]).name
            dst = target / name
            if dst.exists() or dst.is_symlink():
                name = f"{Path(name).stem}__{new_id}{Path(name).suffix}"
                dst = target / name
            if args.copy:
                shutil.copy2(src, dst)
            else:
                dst.symlink_to(src.resolve())
            record = {k: v for k, v in image.items() if k != "id"}
            record.update({"id": new_id, "file_name": name})
            out_images.append(record)
            for ann in by_image.get(image["id"], []):
                out_annotations.append(
                    {
                        "id": next_ann,
                        "image_id": new_id,
                        "category_id": remap[ann["category_id"]],
                        "bbox": [float(v) for v in ann["bbox"]],
                        "area": float(ann.get("area") or ann["bbox"][2] * ann["bbox"][3]),
                        "iscrowd": 0,
                    }
                )
                next_ann += 1
        write_coco(target / "_annotations.coco.json", out_images, out_annotations, DMD_CLASSES)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_coco": str(args.coco.resolve()),
        "out": str(args.out.resolve()),
        "classes": list(DMD_CLASSES),
        "sessions": sessions,
        "images": {s: len(assigned[s]) for s in SPLITS},
        "boxes": {s: dict(counts[s]) for s in SPLITS},
        "images_with_no_boxes": dict(empty),
        "split_rule": (
            "sessions ordered by md5(name), cut at the requested image "
            "fractions; a session is never in two splits"
        ),
    }
    (args.out / "split_report.json").write_text(json.dumps(report, indent=2) + "\n")
    RESULTS.mkdir(exist_ok=True)
    name = args.out.name
    (RESULTS / f"split_{name}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nwrote {args.out} and {RESULTS / f'split_{name}.json'}")
    print(f"\n  next: python finetune.py --data {args.out} --name {name}-v1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
