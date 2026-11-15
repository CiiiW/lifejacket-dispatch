"""Score a checkpoint against labelled ground truth.

    # stock DroneMegaDetector on your labelled NOAA frames
    python evaluate.py --weights dmd \
        --data ~/aerial-data/noaa_eval/_annotations.coco.json --tag noaa-dmd

    # a fine-tune, on the task it was trained for
    python evaluate.py --weights runs/seals-v1/checkpoint_best_total.pth \
        --data ~/aerial-data/seals/test/_annotations.coco.json --tag seals-task

    # ...and the regression check that matters just as much
    python evaluate.py --weights runs/seals-v1/checkpoint_best_total.pth \
        --data ~/aerial-data/noaa_eval/_annotations.coco.json \
        --tag seals-general --compare results/eval_noaa-dmd.json

Reports precision, recall and F1 across a confidence sweep, overall and per
class, plus `blind_images` -- frames that contain the target where nothing was
detected at all. That last column is the one to read first: it is the failure
a coordinator would feel, and it is more honest than mAP about whether a model
is usable.

`--compare` prints a side-by-side against an earlier result. **Run it on every
fine-tune.** A seal model that stopped detecting people is a worse product
than stock DroneMegaDetector, and without this you would ship it not knowing.

Greedy IoU matching at the given threshold, not COCO mAP. Deliberately simple
enough to read in one sitting.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from dmd import (  # noqa: E402
    DEFAULT_SWEEP,
    DMD_CLASSES,
    RESULTS,
    Box,
    best_row,
    format_sweep,
    load_coco,
    load_model,
    predict_images,
    save_json,
    sweep,
)


def filter_class(boxes: list[Box], class_id: int | None) -> list[Box]:
    return boxes if class_id is None else [b for b in boxes if b.class_id == class_id]


def print_comparison(current: dict, baseline: dict) -> list[str]:
    """Side-by-side at each model's own best-F1 threshold."""
    warnings: list[str] = []
    print(f"\n--- vs {baseline.get('tag', 'baseline')} ---")
    print("  class        metric      baseline   current    change")
    for name in ["overall", *DMD_CLASSES]:
        now = current["per_class"].get(name) or (
            current["best"] if name == "overall" else None
        )
        before = baseline["per_class"].get(name) or (
            baseline.get("best") if name == "overall" else None
        )
        if not now or not before:
            continue
        for metric in ("recall", "precision", "f1"):
            a, b = before.get(metric), now.get(metric)
            if a is None or b is None:
                continue
            delta = b - a
            flag = ""
            if delta <= -0.05:
                flag = "  <-- REGRESSION"
                warnings.append(f"{name}/{metric} fell {a:.3f} -> {b:.3f}")
            elif delta >= 0.05:
                flag = "  <-- better"
            print(
                f"  {name:12s} {metric:10s} {a:<10.3f} {b:<10.3f} {delta:+.3f}{flag}"
            )
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--weights", required=True, help="'dmd' for stock DroneMegaDetector, or a .pth path"
    )
    parser.add_argument("--data", type=Path, required=True, help="a COCO annotations file")
    parser.add_argument("--tag", required=True, help="names the output file")
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="inference floor; the sweep filters above it (default: 0.05)",
    )
    parser.add_argument("--resolution", type=int, help="override the checkpoint's resolution")
    parser.add_argument("--limit", type=int, help="first N images only (smoke test)")
    parser.add_argument(
        "--compare", type=Path, help="an earlier results JSON to diff against"
    )
    parser.add_argument("--save-predictions", action="store_true")
    args = parser.parse_args()

    truth_set = load_coco(args.data)
    if len(truth_set) == 0:
        raise SystemExit(f"{args.data} has no images")
    if truth_set.box_count == 0:
        raise SystemExit(
            f"{args.data} has no annotations. Label the frames first -- "
            "prepare_noaa.py writes an empty skeleton on purpose."
        )

    image_ids = sorted(truth_set.images)
    if args.limit:
        image_ids = image_ids[: args.limit]
    paths = [truth_set.image_path(i) for i in image_ids]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"{len(missing)} image files are missing, e.g. {missing[0]}")

    print(f"  {len(paths)} images, {truth_set.box_count} boxes")
    print(f"  ground truth: {truth_set.per_class_counts()}")

    weights = None if args.weights.lower() == "dmd" else args.weights
    model = load_model(weights, resolution=args.resolution)
    predictions = predict_images(model, paths, threshold=args.threshold)

    per_image_all = [
        (predictions[truth_set.image_path(i)], truth_set.boxes.get(i, [])) for i in image_ids
    ]
    overall = sweep(per_image_all, args.iou, DEFAULT_SWEEP)
    print("\n--- all classes ---")
    print(format_sweep(overall))
    overall_best = best_row(overall)
    print(
        f"\n  best F1 {overall_best['f1']:.3f} at confidence "
        f"{overall_best['confidence']:.2f}"
    )

    per_class: dict[str, dict] = {}
    for class_id, name in enumerate(DMD_CLASSES):
        truth_count = sum(
            len(filter_class(truth_set.boxes.get(i, []), class_id)) for i in image_ids
        )
        if truth_count == 0:
            continue
        rows = sweep(
            [
                (
                    filter_class(predictions[truth_set.image_path(i)], class_id),
                    filter_class(truth_set.boxes.get(i, []), class_id),
                )
                for i in image_ids
            ],
            args.iou,
            DEFAULT_SWEEP,
        )
        best = best_row(rows)
        per_class[name] = {**best, "ground_truth_boxes": truth_count, "sweep": rows}
        print(f"\n--- {name} ({truth_count} boxes) ---")
        print(format_sweep(rows))

    print("\n  summary, each at its own best-F1 threshold:")
    print("  class        conf    P       R       F1      blind")
    for name, row in per_class.items():
        print(
            f"  {name:12s} {row['confidence']:<7.2f} {row['precision']:<7.3f} "
            f"{row['recall']:<7.3f} {row['f1']:<7.3f} {row['blind_images']}"
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tag": args.tag,
        "weights": args.weights,
        "data": str(args.data.resolve()),
        "classes": list(DMD_CLASSES),
        "images": len(paths),
        "iou_threshold": args.iou,
        "ground_truth": truth_set.per_class_counts(),
        "best": overall_best,
        "sweep": overall,
        "per_class": per_class,
        "method": "greedy IoU matching, highest confidence first; not COCO mAP",
    }
    if args.save_predictions:
        payload["predictions"] = {
            truth_set.image_path(i).name: [
                {
                    "box": [b.x1, b.y1, b.x2, b.y2],
                    "score": round(b.score, 4),
                    "class": b.class_name,
                }
                for b in predictions[truth_set.image_path(i)]
            ]
            for i in image_ids
        }

    warnings: list[str] = []
    if args.compare:
        if not args.compare.exists():
            print(f"\n  --compare: {args.compare} not found, skipping")
        else:
            warnings = print_comparison(payload, json.loads(args.compare.read_text()))
            payload["compared_with"] = str(args.compare)
            payload["regressions"] = warnings

    save_json(payload, RESULTS / f"eval_{args.tag}.json")

    if warnings:
        print("\n  REGRESSIONS (a drop of 0.05 or more):")
        for warning in warnings:
            print(f"    {warning}")
        print(
            "\n  A specialised model that lost a general class is usually worse\n"
            "  in the field than the base model. Add or raise --replay in\n"
            "  finetune.py and train again before publishing this."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
