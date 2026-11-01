"""Conservative, disposable association suggestions, not animal identities."""

from collections import Counter

from lifejacket.models.drone_demo import DemoFrameMetadata

METHOD = "box-overlap-v1"
MAX_GAP_SECONDS = 3.0
MIN_IOU = 0.5


def overlap(a, b):
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    return intersection / (area_a + area_b - intersection)


def suggest_groups(frames):
    """Same-clip suggestions; ambiguous matches split, no identities asserted."""
    if not 1 <= len(frames) <= 60:
        raise ValueError("Expected 1 to 60 imported source frames")
    parsed = [(frame, DemoFrameMetadata.model_validate(frame["metadata"])) for frame in frames]
    if len({(m.source_sha256, m.evidence_kind) for _, m in parsed}) != 1:
        raise ValueError("Group one source and evidence kind at a time")
    if len({m.offset_seconds for _, m in parsed}) != len(parsed):
        raise ValueError("Duplicate source timestamps")
    parsed.sort(key=lambda pair: pair[1].offset_seconds)
    groups, active, warnings = [], [], []
    excluded = 0
    for frame, metadata in parsed:
        if frame["status"] == "rejected":
            excluded += 1
            continue
        time = metadata.offset_seconds
        active = [track for track in active if time - track["time"] <= MAX_GAP_SECONDS]
        if metadata.detection_status != "completed":
            warnings.append({"demo_id": frame["demo_id"], "reason": metadata.detection_status})
            continue
        candidates = []
        for index, animal in enumerate(metadata.detection.animals):
            box = animal.box
            if box[0] >= box[2] or box[1] >= box[3]:
                warnings.append(
                    {
                        "demo_id": frame["demo_id"],
                        "candidate_index": index,
                        "reason": "invalid_box",
                    }
                )
                continue
            candidates.append((index, animal))
        edges = [
            (i, j)
            for i, track in enumerate(active)
            for j, (_, animal) in enumerate(candidates)
            if track["kind"] == animal.kind and overlap(track["box"], animal.box) >= MIN_IOU
        ]
        left, right = Counter(i for i, _ in edges), Counter(j for _, j in edges)
        matches = {j: i for i, j in edges if left[i] == right[j] == 1}
        ambiguous = {j for i, j in edges if left[i] != 1 or right[j] != 1}
        retired = {i for i, j in edges if j in ambiguous}
        next_active = [
            track
            for i, track in enumerate(active)
            if i not in retired and i not in matches.values()
        ]
        for j, (index, animal) in enumerate(candidates):
            member = {
                "demo_id": frame["demo_id"],
                "candidate_index": index,
                "offset_seconds": time,
                "box": animal.box,
                "frame_revision": frame["revision"],
            }
            if j in matches:
                group = active[matches[j]]["group"]
            else:
                group = {
                    "group_id": f"suggestion-{len(groups) + 1}",
                    "kind": animal.kind,
                    "association": "ambiguous" if j in ambiguous else "provisional",
                    "members": [],
                }
                groups.append(group)
            group["members"].append(member)
            next_active.append(
                {"time": time, "box": animal.box, "kind": animal.kind, "group": group}
            )
        active = next_active
    return {
        "method": METHOD,
        "demo_only": True,
        "persisted": False,
        "max_gap_seconds": MAX_GAP_SECONDS,
        "minimum_iou": MIN_IOU,
        "source_sha256": parsed[0][1].source_sha256,
        "evidence_kind": parsed[0][1].evidence_kind,
        "frame_count": len(parsed),
        "excluded_rejected_frames": excluded,
        "groups": groups,
        "warnings": warnings,
        "notice": (
            "Provisional associations, not distinct animal counts. "
            "Review source frames; camera motion, crossings and re-entry "
            "can cause wrong merges or splits."
        ),
    }
