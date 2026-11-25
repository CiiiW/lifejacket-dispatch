"""Fine-tune DroneMegaDetector for a more specific search.

    # a model that finds seals on a beach reliably
    python finetune.py --data ~/aerial-data/seals --name seals-v1

    # a model that finds birds, which stock DMD is explicitly weak at
    python finetune.py --data ~/aerial-data/birds --name birds-v1 --epochs 60

    # resume after a Spot preemption
    python finetune.py --data ~/aerial-data/seals --name seals-v1 --resume

Every fine-tune keeps DroneMegaDetector's three classes in its order --
person, animal, vehicle. A seal model is not a model with a `seal` class; it
is a model whose `animal` class finds seals reliably. That keeps every
checkpoint a drop-in replacement for every other: one decode path, one
`CLASS_NAMES`, and swapping models is three environment variables.

Species naming is not this model's job. The identification agent already does
it, on a cropped frame, through `taxonomy.py`.

**Replay.** Fine-tuning only on seals makes the model better at seals and
worse at everything else, including person and vehicle, which every site
needs. `--replay DIR` mixes a slice of general data into training to hold that
off. Use it unless you have a reason not to.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from dmd import DMD_CLASSES, DMD_PATCH_SIZE, ensure_dmd_weights  # noqa: E402

RUNS = HERE / "runs"
SPLITS = ("train", "valid")


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def check_layout(data: Path) -> dict[str, int]:
    """rfdetr wants <split>/_annotations.coco.json. Fail now, not in epoch 1."""
    counts = {}
    for split in SPLITS:
        annotations = data / split / "_annotations.coco.json"
        if not annotations.exists():
            raise SystemExit(
                f"missing {annotations}\n"
                "rfdetr expects train/ and valid/ directories, each with an\n"
                "_annotations.coco.json beside its images. Build one with:\n"
                f"  python dataset.py --coco LABELLED.json --images DIR --out {data}"
            )
        doc = json.loads(annotations.read_text())
        names = [c["name"] for c in sorted(doc.get("categories", []), key=lambda c: c["id"])]
        if tuple(names) != DMD_CLASSES:
            raise SystemExit(
                f"{annotations} categories are {names}, expected {list(DMD_CLASSES)} "
                "in that order. dataset.py writes them correctly; a raw export "
                "from a labelling tool usually does not."
            )
        counts[split] = len(doc.get("images", []))
        if counts[split] == 0:
            raise SystemExit(f"{annotations} has no images")
    return counts


def merge_replay(data: Path, replay: Path, fraction: float, work: Path) -> Path:
    """Build a training set that is `fraction` general data, the rest specific.

    Guards against catastrophic forgetting. Only the train split is mixed --
    validation stays purely task-specific, because what you want to know is
    whether the model got better at *this* job.
    """
    import random

    specific = json.loads((data / "train" / "_annotations.coco.json").read_text())
    general = json.loads((replay / "train" / "_annotations.coco.json").read_text())

    want = int(len(specific["images"]) * fraction / max(1e-9, 1 - fraction))
    want = min(want, len(general["images"]))
    if want == 0:
        print("  replay: nothing to mix in, using the specific set alone")
        return data

    random.seed(0)
    picked = random.sample(general["images"], want)
    picked_ids = {image["id"] for image in picked}

    merged = work / "train"
    merged.mkdir(parents=True, exist_ok=True)
    images, annotations = list(specific["images"]), list(specific["annotations"])
    next_image = max((i["id"] for i in images), default=0) + 1
    next_ann = max((a["id"] for a in annotations), default=0) + 1

    for image in picked:
        source = replay / "train" / image["file_name"]
        if not source.exists():
            continue
        name = f"replay__{image['file_name']}"
        link = merged / name
        if not link.exists():
            link.symlink_to(source.resolve())
        record = dict(image)
        record.update({"id": next_image, "file_name": name})
        images.append(record)
        for ann in general["annotations"]:
            if ann["image_id"] not in picked_ids or ann["image_id"] != image["id"]:
                continue
            copy = dict(ann)
            copy.update({"id": next_ann, "image_id": next_image})
            annotations.append(copy)
            next_ann += 1
        next_image += 1

    for image in specific["images"]:
        source = data / "train" / image["file_name"]
        link = merged / image["file_name"]
        if source.exists() and not link.exists():
            link.symlink_to(source.resolve())

    doc = dict(specific)
    doc["images"], doc["annotations"] = images, annotations
    (merged / "_annotations.coco.json").write_text(json.dumps(doc, indent=2) + "\n")

    valid_link = work / "valid"
    if not valid_link.exists():
        valid_link.symlink_to((data / "valid").resolve())
    test_dir = data / "test"
    if test_dir.exists() and not (work / "test").exists():
        (work / "test").symlink_to(test_dir.resolve())

    print(
        f"  replay: {len(specific['images'])} specific + {want} general "
        f"= {len(images)} training images"
    )
    return work


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", type=Path, required=True, help="dir from dataset.py")
    parser.add_argument("--name", required=True, help="run directory name under runs/")
    parser.add_argument(
        "--base",
        help="starting checkpoint. Default: stock DroneMegaDetector. Pass a "
        "previous fine-tune's path to continue specialising it",
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument(
        "--batch-size",
        default="auto",
        help="'auto' lets rfdetr size it to the GPU (default: auto)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=1e-4,
        help="rfdetr's default. Lower it to 5e-5 if the model forgets",
    )
    parser.add_argument(
        "--resolution",
        type=int,
        help="override the input resolution. Must be a multiple of 56. Leave "
        "unset and the checkpoint's own trained resolution is used, which is "
        "almost always what you want",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        help="a general dataset dir to mix into training, against forgetting",
    )
    parser.add_argument(
        "--replay-fraction",
        type=float,
        default=0.25,
        help="share of training images drawn from --replay (default: 0.25)",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="check everything, train nothing"
    )
    args = parser.parse_args()

    if args.resolution is not None and args.resolution % DMD_PATCH_SIZE != 0:
        # DroneMegaDetector's backbone uses patch size 16 and was trained at
        # 1280. Some RF-DETR variants want multiples of 56 instead; 1280 is
        # not one, which is why this checks the checkpoint's patch size rather
        # than a number copied out of the docs.
        parser.error(
            f"--resolution must be a multiple of {DMD_PATCH_SIZE} (the backbone "
            f"patch size); {args.resolution} is not. Nearby: "
            f"{args.resolution // DMD_PATCH_SIZE * DMD_PATCH_SIZE} or "
            f"{(args.resolution // DMD_PATCH_SIZE + 1) * DMD_PATCH_SIZE}."
        )
    if not 0.0 <= args.replay_fraction < 1.0:
        parser.error("--replay-fraction must be in [0, 1)")

    counts = check_layout(args.data)
    print(f"  dataset: {counts['train']} train, {counts['valid']} valid images")
    print(f"  classes: {list(DMD_CLASSES)}")

    RUNS.mkdir(exist_ok=True)
    run_dir = RUNS / args.name
    if run_dir.exists() and not args.resume:
        raise SystemExit(f"{run_dir} exists. Choose another --name or pass --resume.")

    data_dir = args.data
    if args.replay:
        check_layout(args.replay)
        work = run_dir / "merged"
        if work.exists():
            shutil.rmtree(work)
        data_dir = merge_replay(args.data, args.replay, args.replay_fraction, work)

    base = Path(args.base) if args.base else ensure_dmd_weights()
    provenance = {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "base_weights": str(base),
        "base_is_stock_dmd": args.base is None,
        "classes": list(DMD_CLASSES),
        "data": str(args.data.resolve()),
        "effective_data": str(Path(data_dir).resolve()),
        "replay": str(args.replay.resolve()) if args.replay else None,
        "replay_fraction": args.replay_fraction if args.replay else 0.0,
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "image_counts": counts,
    }

    if args.dry_run:
        print("\n--dry-run: layout, classes and base weights all check out.")
        print(json.dumps(provenance, indent=2))
        return 0

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(provenance, indent=2) + "\n")

    from rfdetr import RFDETRMedium

    kwargs = {"pretrain_weights": str(base)}
    if args.resolution:
        kwargs["resolution"] = args.resolution
    model = RFDETRMedium(**kwargs)
    batch_size = args.batch_size
    if isinstance(batch_size, str) and batch_size != "auto":
        batch_size = int(batch_size)

    print(f"\n  fine-tuning from {base.name}")
    resolution_note = args.resolution or "from checkpoint"
    print(f"  {args.epochs} epochs, lr {args.lr}, resolution {resolution_note}")
    model.train(
        dataset_dir=str(Path(data_dir).resolve()),
        epochs=args.epochs,
        batch_size=batch_size,
        lr=args.lr,
        output_dir=str(run_dir),
        resume=args.resume,
    )

    provenance["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    candidates = sorted(run_dir.glob("checkpoint_best*.pth")) or sorted(run_dir.glob("*.pth"))
    provenance["best_weights"] = str(candidates[0]) if candidates else None
    (run_dir / "run.json").write_text(json.dumps(provenance, indent=2) + "\n")

    print(f"\n  run directory: {run_dir}")
    if candidates:
        print(f"  best weights:  {candidates[0]}")
    print("\n  next, and do BOTH:")
    print(f"    python evaluate.py --weights {candidates[0] if candidates else 'BEST.pth'} \\")
    print(f"        --data {args.data}/test/_annotations.coco.json --tag {args.name}-task")
    print("    # ...and check it did not regress on general data:")
    print("    python evaluate.py --weights ... \\")
    print("        --data GENERAL/test/_annotations.coco.json \\")
    print(f"        --tag {args.name}-general --compare results/eval_noaa-dmd.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
