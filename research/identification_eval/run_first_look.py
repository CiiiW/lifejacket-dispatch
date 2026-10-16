"""First look: run the identification prompt once on every test photo and score it.

    python run_first_look.py                    # originals, then every variant
    python run_first_look.py --only originals   # just the clean photos
    python run_first_look.py --limit 5          # smoke test: first 5 images
    python run_first_look.py --dry-run          # scripted fake model, no credentials
    python run_first_look.py --resume results/first_look_<time>.csv
    python run_first_look.py --targets selected_animals.csv

Needs `gcloud auth application-default login` (not for --dry-run).

"First look" means one model call per image, with no questions answered: it
measures what the prompt makes of the photo itself. The call goes through the
real pipeline (ChatPlayground.identification_only), so the same code decides
what the system would do next, and `chat_triggered` says whether the chatbot
would have started asking questions (or asked for a new photo).

Each run writes four files into results/, named first_look_<time>:

    .csv          the one to open: image, variant, truth, what the model said, how it
                  did, and what the system does next
    _detail.csv   the same rows with every column, for analysis (the summary reads it)
    .jsonl        the model's raw reply for every image, for reading one case closely
    .meta.json    the prompt hash, git commit, model and settings of the run

Rows are written as they finish, so an interrupted run loses nothing; use
--resume to carry on where it stopped.

How an answer is scored against manifest.csv:

    top1_*_correct     the highest-probability candidate vs the truth, at species,
                       genus, family and animal group. Species matches on the
                       scientific name or the common name, compared strictly after
                       normalising ("Harbour"/"Harbor" and "Steller's"/"Steller"
                       agree; "Common dolphin" and "Common Bottlenose Dolphin" do not).
    p_truth            probability the model gave the true species, summed over its
                       candidates.
    resolved_correct   the system's final answer (taxonomy.resolve_taxon) is correct
                       *at the rank it settled on*: "oceanic dolphins" is correct for
                       a common dolphin even though it is less specific.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from lifejacket.chatbot.playground import ChatPlayground  # noqa: E402
from lifejacket.chatbot.session import StepAction  # noqa: E402
from lifejacket.config import settings  # noqa: E402
from lifejacket.context.geocode import reverse_geocode  # noqa: E402
from lifejacket.llm.fake import ScriptedLLMClient  # noqa: E402

MANIFEST = HERE / "manifest.csv"
PHOTOS = HERE / "photos"
VARIANTS = HERE / "variants"
DEFAULT_OUT = HERE / "results"
PROMPT_FILES = [
    REPO_ROOT / "prompts" / "identification" / "identify_species.md",
    REPO_ROOT / "prompts" / "system_principles.md",
]

FIELDS = [
    "case_id", "variant_type", "level", "image_file",
    "truth_common", "truth_scientific", "truth_genus", "truth_family", "truth_group",
    "latitude", "longitude", "place_name",
    "top1_common", "top1_scientific", "top1_genus", "top1_family", "top1_group",
    "top1_confidence", "candidates",
    "top1_species_correct", "top1_genus_correct", "top1_family_correct",
    "top1_group_correct", "p_truth",
    "resolved_rank", "resolved_name", "resolved_confidence", "resolved_meets_threshold",
    "resolved_correct", "truth_in_members",
    "next_action", "chat_triggered", "stop_reason", "needs_new_photo",
    "species_distinguishable", "next_question", "next_question_feature",
    "detected_count", "selected_animal", "detection_status",
    "latency_s", "prompt_tokens", "output_tokens", "attempts", "error",
]


# --- Name matching -------------------------------------------------------------


def norm(text: str | None) -> str:
    """Lower-case, drop brackets and possessives, unify British/American spellings."""
    text = re.sub(r"\(.*?\)", " ", (text or "").lower())
    text = re.sub(r"['’]s\b", "", text)
    text = text.replace("grey", "gray").replace("harbour", "harbor")
    words = re.sub(r"[^a-z0-9 ]", " ", text).split()
    # iNaturalist writes "Common Bottlenose Dolphin" where a model writes "Bottlenose
    # dolphin". Dropping a leading "common" reconciles them, and leaves "Common
    # dolphin" (two words) alone, so it does NOT match a bottlenose dolphin.
    if len(words) > 2 and words[0] == "common":
        words = words[1:]
    return " ".join(words)


def same_name(a: str | None, b: str | None) -> bool:
    """Equal after normalising. Deliberately strict: a loose match would hide errors
    between look-alikes, which are the cases this test exists to catch."""
    return bool(norm(a)) and norm(a) == norm(b)


def is_truth_species(scientific: str | None, common: str | None, truth: dict) -> bool:
    return same_name(scientific, truth["scientific"]) or same_name(common, truth["common"])


def genus_of(candidate) -> str:
    return candidate.genus or (candidate.scientific_name or "").split(" ")[0]


# --- Scoring one result --------------------------------------------------------


def resolved_is_correct(resolution, truth: dict) -> bool:
    """Is the truth inside the taxon the system settled on?"""
    if resolution is None:
        return False
    rank = resolution.rank.value
    if rank == "species":
        return is_truth_species(resolution.scientific_name, resolution.name, truth)
    if rank == "genus":
        return norm(resolution.scientific_name) == norm(truth["genus"])
    if rank == "family":
        return norm(resolution.scientific_name) == norm(truth["family"])
    if rank == "group":
        return resolution.animal_group.value == truth["group"]
    return False


def score(chat, truth: dict) -> dict:
    """Flatten what the identification step produced into one result row."""
    state = chat.state
    result = state.identification
    turn = chat.last_turn
    metrics = chat.pipeline.identification_agent.last_metrics

    row: dict = {
        "detected_count": len(state.detections or []),
        "selected_animal": (
            state.selected_detection + 1 if state.selected_detection is not None else ""
        ),
        "detection_status": state.detection_status,
        "next_action": turn.action.value if turn.action else "",
        "chat_triggered": turn.action
        in (StepAction.ASK_CLARIFYING_QUESTION, StepAction.REQUEST_BETTER_PHOTO),
        "stop_reason": state.identification_stop_reason or turn.reason,
        "latency_s": metrics.get("identification_latency_seconds"),
        "prompt_tokens": metrics.get("identification_prompt_tokens"),
        "output_tokens": metrics.get("identification_output_tokens"),
        "attempts": metrics.get("identification_attempts"),
    }
    if result is None:
        row["error"] = (
            "selection_required" if turn.action is StepAction.ASK_WHICH_ANIMAL
            else "identification_unavailable"
        )
        return row

    candidates = sorted(result.candidates, key=lambda c: c.confidence, reverse=True)
    top = candidates[0] if candidates else None
    resolution = result.resolution
    correct = resolved_is_correct(resolution, truth)

    row.update({
        "candidates": "; ".join(f"{c.common_name} {c.confidence:.2f}" for c in candidates),
        "p_truth": round(sum(
            c.confidence for c in candidates
            if is_truth_species(c.scientific_name, c.common_name, truth)
        ), 4),
        "needs_new_photo": result.needs_new_photo,
        "species_distinguishable": result.species_distinguishable,
        "next_question": result.next_question.question if result.next_question else "",
        "next_question_feature": result.next_question.feature if result.next_question else "",
    })
    if top:
        row.update({
            "top1_common": top.common_name,
            "top1_scientific": top.scientific_name or "",
            "top1_genus": genus_of(top),
            "top1_family": top.family or "",
            "top1_group": top.animal_group.value,
            "top1_confidence": top.confidence,
            "top1_species_correct": is_truth_species(
                top.scientific_name, top.common_name, truth),
            "top1_genus_correct": norm(genus_of(top)) == norm(truth["genus"]),
            "top1_family_correct": norm(top.family) == norm(truth["family"]),
            "top1_group_correct": top.animal_group.value == truth["group"],
        })
    if resolution:
        row.update({
            "resolved_rank": resolution.rank.value,
            "resolved_name": resolution.name,
            "resolved_confidence": resolution.confidence,
            "resolved_meets_threshold": resolution.meets_threshold,
            "resolved_correct": correct,
            "truth_in_members": any(
                is_truth_species(m.scientific_name, m.common_name, truth)
                for m in resolution.members
            ),
        })
    return row


# --- Inputs --------------------------------------------------------------------


def load_items(only: str) -> tuple[list[dict], dict[str, dict]]:
    """Every image to run (originals first, so a partial run still gives a baseline)."""
    truths: dict[str, dict] = {}
    items: list[dict] = []
    with open(MANIFEST, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            truths[row["case_id"]] = {
                "common": row["species_common"], "scientific": row["species_scientific"],
                "genus": row["genus"], "family": row["family"], "group": row["animal_group"],
                "latitude": float(row["latitude"]), "longitude": float(row["longitude"]),
            }
            if (PHOTOS / row["file"]).exists():
                items.append({"case_id": row["case_id"], "variant_type": "original",
                              "level": 0, "path": PHOTOS / row["file"]})

    variant_index = VARIANTS / "variants.csv"
    if variant_index.exists():
        with open(variant_index, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                path = VARIANTS / row["variant_file"]
                if row["case_id"] in truths and path.exists():
                    items.append({"case_id": row["case_id"], "path": path,
                                  "variant_type": row["variant_type"],
                                  "level": int(row["level"])})

    if only == "originals":
        items = [i for i in items if i["variant_type"] == "original"]
    elif only == "variants":
        items = [i for i in items if i["variant_type"] != "original"]
    return items, truths


def load_targets(path: Path | None) -> dict[tuple[str, str, int], int]:
    """Explicit 1-based animal choices, keyed by image and variant.

    A case's true species is not sufficient to infer which box contains the
    labelled animal. An unlabelled multi-animal photo must remain unscored.
    """
    if path is None:
        return {}
    targets: dict[tuple[str, str, int], int] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["case_id"], row["variant_type"], int(row["level"]))
            if key in targets:
                raise ValueError(f"Duplicate target choice for {key}")
            number = int(row["animal_number"])
            if number < 1:
                raise ValueError(f"Animal number must be positive for {key}")
            targets[key] = number
    return targets


class PlaceNames:
    """Reverse-geocode each case once, the way the live app does, within Nominatim's limit."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.names: dict[str, str | None] = {}

    def get(self, case_id: str, latitude: float, longitude: float) -> str | None:
        if not self.enabled:
            return None
        if case_id not in self.names:
            misses = reverse_geocode.cache_info().misses
            place = reverse_geocode(round(latitude, 5), round(longitude, 5))
            if reverse_geocode.cache_info().misses > misses:
                time.sleep(1.1)  # at most one request a second
            self.names[case_id] = place.display_name if place else None
        return self.names[case_id]


def git_state() -> dict:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()

    return {
        "commit": run("rev-parse", "--short", "HEAD"),
        "uncommitted_changes_in_prompts_or_backend": bool(
            run("status", "--porcelain", "--", "prompts", "backend")),
    }


def write_meta(path: Path, args: argparse.Namespace, total: int, finished: bool) -> None:
    # A resumed run keeps the original start time and lists when it was resumed.
    earlier = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    now = datetime.now().isoformat(timespec="seconds")
    resumed = earlier.get("resumed_at", []) + ([now] if args.resume and not finished else [])
    meta = {
        "started": earlier.get("started", now),
        "resumed_at": resumed,
        "finished": finished,
        "images_planned": total,
        "args": {k: str(v) for k, v in vars(args).items()},
        "git": git_state(),
        "prompt_files_sha256": {
            f.name: hashlib.sha256(f.read_bytes()).hexdigest()[:12] for f in PROMPT_FILES
        },
        "model": "scripted-offline" if args.dry_run else settings.llm_model,
        "temperature": 0.1,  # IdentificationAgent.temperature
        "thinking_budget": settings.llm_thinking_budget,
        "max_output_tokens": settings.llm_max_output_tokens,
        "identification_confidence_threshold": settings.identification_confidence_threshold,
        "confident_taxon_ranks": settings.confident_taxon_ranks,
        "identification_min_confidence_to_settle":
            settings.identification_min_confidence_to_settle,
        "location_text": "location line only (no tide, weather or time)",
    }
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def print_summary(csv_path: Path) -> None:
    df = pd.read_csv(csv_path).drop_duplicates(
        ["case_id", "variant_type", "level"], keep="last")
    failed = df["error"].notna().sum()
    ok = df[df["error"].isna()]
    if ok.empty:
        print("No successful results to summarise.")
        return
    table = ok.groupby("variant_type").agg(
        n=("case_id", "size"),
        species=("top1_species_correct", "mean"),
        genus=("top1_genus_correct", "mean"),
        family=("top1_family_correct", "mean"),
        group=("top1_group_correct", "mean"),
        resolved=("resolved_correct", "mean"),
        chat=("chat_triggered", "mean"),
    )
    order = ["original"] + sorted(set(table.index) - {"original"})
    print("\nTop-1 accuracy by image type (resolved = system's final answer at its own rank;")
    print("chat = share of images that would start a chat):\n")
    print(table.reindex([o for o in order if o in table.index]).to_string(
        float_format=lambda x: f"{x:.2f}"))
    print(f"\n{len(ok)} images scored, {failed} failed. Results are in {csv_path.parent}")


# --- The readable CSV ----------------------------------------------------------

READABLE_FIELDS = ["image", "variant", "truth", "model_says", "result", "next_step"]


def detail_path_of(csv_path: Path) -> Path:
    """The full-column CSV that sits beside the readable one."""
    return csv_path.with_name(csv_path.stem + "_detail.csv")


def describe_result(row: dict) -> str:
    """The outcome in a few words, by the most specific level the top answer got right."""
    if row.get("error"):
        return "ERROR"
    if "top1_common" not in row:
        return "no answer"
    if row.get("top1_species_correct"):
        return "species correct"
    gave = f"(truth got {row.get('p_truth') or 0:.2f})"
    if row.get("top1_genus_correct"):
        return f"genus correct, species wrong {gave}"
    if row.get("top1_family_correct"):
        return f"family correct only {gave}"
    if row.get("top1_group_correct"):
        return f"animal group correct only {gave}"
    return f"wrong animal group {gave}"


def describe_next_step(row: dict) -> str:
    """What the system does after this first look: settle, ask, or ask for a new photo."""
    if row.get("error"):
        return str(row["error"])
    action = row.get("next_action")
    if action == StepAction.ASK_CLARIFYING_QUESTION.value:
        return f"asks: {row.get('next_question', '')}"
    if action == StepAction.REQUEST_BETTER_PHOTO.value:
        return f"asks for a new photo: {row.get('stop_reason', '')}"
    verdict = "right" if row.get("resolved_correct") else "WRONG"
    return (
        f"settles at {row.get('resolved_rank')}: {row.get('resolved_name')} "
        f"{row.get('resolved_confidence', 0):.2f} ({verdict})"
    )


def readable_row(row: dict) -> dict:
    variant = "original" if row["variant_type"] == "original" else (
        f"{row['variant_type']} {row['level']}")
    return {
        "image": row["case_id"],
        "variant": variant,
        "truth": row["truth_common"],
        "model_says": row.get("candidates", ""),
        "result": describe_result(row),
        "next_step": describe_next_step(row),
    }


# --- Main ----------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", choices=["all", "originals", "variants"], default="all")
    parser.add_argument("--limit", type=int, help="run only the first N images")
    parser.add_argument("--resume", type=Path, help="results CSV from an interrupted run")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true",
                        help="scripted fake model and no geocoding; needs no credentials")
    parser.add_argument("--no-place-names", action="store_true",
                        help="give the model coordinates only (skips Nominatim)")
    parser.add_argument("--targets", type=Path,
                        help="CSV with case_id,variant_type,level,animal_number (1-based)")
    args = parser.parse_args()
    targets = load_targets(args.targets)

    items, truths = load_items(args.only)
    if args.limit:
        items = items[: args.limit]
    if not items:
        sys.exit("No images found. Run download_photos.py (and make_variants.py) first.")

    if not args.dry_run:
        import google.auth

        _, project = google.auth.default()  # raises if you have not logged in
        print("Vertex AI credentials found for project:", project)

    if args.resume:
        csv_path = Path(str(args.resume).replace("_detail.csv", ".csv"))
        if not detail_path_of(csv_path).exists():
            sys.exit(f"Cannot resume: {detail_path_of(csv_path).name} is missing.")
        with open(detail_path_of(csv_path), newline="", encoding="utf-8") as fh:
            done = {
                (r["case_id"], r["variant_type"], int(r["level"]))
                for r in csv.DictReader(fh)
                if not r["error"]
            }
        items = [i for i in items if (i["case_id"], i["variant_type"], i["level"]) not in done]
        print(f"Resuming: {len(done)} already done, {len(items)} to go.")
    else:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = args.out_dir / f"first_look_{datetime.now():%Y%m%d_%H%M%S}.csv"
    jsonl_path = csv_path.with_suffix(".jsonl")
    write_meta(csv_path.with_suffix(".meta.json"), args, len(items), finished=False)

    places = PlaceNames(enabled=not (args.dry_run or args.no_place_names))

    def make_client():
        """A fresh scripted client per image in a dry run; otherwise the real one."""
        return ScriptedLLMClient.scenario("sea_lion") if args.dry_run else None

    is_new_file = not csv_path.exists()
    started = time.monotonic()

    with open(csv_path, "a", newline="", encoding="utf-8") as readable_fh, \
            open(detail_path_of(csv_path), "a", newline="", encoding="utf-8") as csv_fh, \
            open(jsonl_path, "a", encoding="utf-8") as raw_fh:
        readable = csv.DictWriter(readable_fh, fieldnames=READABLE_FIELDS)
        writer = csv.DictWriter(csv_fh, fieldnames=FIELDS)
        if is_new_file:
            readable.writeheader()
            writer.writeheader()

        try:
            for number, item in enumerate(items, start=1):
                truth = truths[item["case_id"]]
                place = places.get(item["case_id"], truth["latitude"], truth["longitude"])
                row = {
                    "case_id": item["case_id"], "variant_type": item["variant_type"],
                    "level": item["level"], "image_file": item["path"].name,
                    "truth_common": truth["common"], "truth_scientific": truth["scientific"],
                    "truth_genus": truth["genus"], "truth_family": truth["family"],
                    "truth_group": truth["group"], "latitude": truth["latitude"],
                    "longitude": truth["longitude"], "place_name": place or "",
                }
                raw = None
                try:
                    chat = ChatPlayground.identification_only(
                        photos=[item["path"]], latitude=truth["latitude"],
                        longitude=truth["longitude"], place_name=place,
                        client=make_client(), live_context=False, verbose=False,
                    )
                    if chat.last_turn.action is StepAction.ASK_WHICH_ANIMAL:
                        key = (item["case_id"], item["variant_type"], item["level"])
                        if key in targets:
                            chat.select(targets[key])
                    row.update(score(chat, truth))
                    raw = chat.last_response("identification")
                except Exception as exc:  # noqa: BLE001 - record it and keep going
                    row["error"] = f"{type(exc).__name__}: {exc}"[:300]

                writer.writerow({k: row.get(k, "") for k in FIELDS})
                readable.writerow(readable_row(row))
                csv_fh.flush()
                readable_fh.flush()
                raw_fh.write(json.dumps({
                    "case_id": item["case_id"], "variant_type": item["variant_type"],
                    "level": item["level"], "error": row.get("error"), "response": raw,
                }) + "\n")
                raw_fh.flush()

                verdict = row.get("error") or (
                    f"{row.get('top1_common', '?')} {row.get('top1_confidence', 0):.2f}  "
                    f"resolved {row.get('resolved_rank', '?')} "
                    f"{'OK' if row.get('resolved_correct') else 'WRONG'}"
                )
                label = f"{item['variant_type']}_{item['level']}"
                print(f"[{number}/{len(items)}] {item['case_id']:<32} {label:<12} {verdict}")
        except KeyboardInterrupt:
            print("\nInterrupted. Continue with:")
            print(f"  python run_first_look.py --resume {csv_path}")
            return

    write_meta(csv_path.with_suffix(".meta.json"), args, len(items), finished=True)
    print(f"\nDone in {(time.monotonic() - started) / 60:.1f} minutes.")
    print_summary(detail_path_of(csv_path))


if __name__ == "__main__":
    main()
