"""Static box overlays and provisional, model-exposed manual review sheets."""

import hashlib
import html
import json
import math
import re
from pathlib import Path


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _box(value):
    if not isinstance(value, list) or len(value) != 4:
        return None
    if any(
        isinstance(n, bool)
        or not isinstance(n, (int, float))
        or not math.isfinite(n)
        or not 0 <= n <= 1000
        for n in value
    ):
        return None
    y1, x1, y2, x2 = value
    return value if y1 < y2 and x1 < x2 else None


def render_review(root: Path, manifest: dict, results: dict | None = None):
    manifest_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    if json.loads((root / "manifest.json").read_text()) != manifest:
        raise ValueError("Review manifest does not match saved evidence")
    if results and results.get("manifest_sha256") != manifest_hash:
        raise ValueError("Review detection belongs to a different manifest")
    statuses = {}
    for row in (results or {}).get("frames", []):
        if row["path"] in statuses:
            raise ValueError("Duplicate detection frame")
        statuses[row["path"]] = row
    cards, records, links = [], [], []
    for index, frame in enumerate(manifest["frames"]):
        path = frame["path"]
        if not re.fullmatch(r"frames/\d{4}\.jpg", path):
            raise ValueError("Invalid frame path")
        status = statuses.get(path)
        detected = bool(status and status["status"] == "detected")
        animals = status["animals"] if detected else []
        label = (
            f"{len(animals)} candidate region(s); human review needed"
            if detected
            else "Detection failed"
            if status
            else "Not analyzed"
        )
        boxes, regions = [], []
        for number, animal in enumerate(animals, 1):
            box = _box(animal.get("box"))
            if box:
                y1, x1, y2, x2 = box
                boxes.append(
                    f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}"/>'
                    f'<text x="{x1 + 3}" y="{max(22, y1 + 24)}">{number}</text>'
                )
            regions.append(
                f"<li><b>Region {number}</b>: {html.escape(animal.get('description', ''))}"
                f" ({html.escape(animal.get('kind', 'other'))})"
                + ("" if box else " · Invalid box: overlay omitted")
                + f'<label>Region {number} review <select data-region="{number - 1}">'
                '<option value="unreviewed">Not reviewed</option>'
                '<option value="individual">Possible individual animal</option>'
                '<option value="group">Possible group / colony</option>'
                '<option value="not_animal">Not an animal</option>'
                '<option value="uncertain">Uncertain</option></select></label></li>'
            )
        offset = frame["offset_seconds"]
        records.append(
            {
                "path": path,
                "frame_sha256": frame["sha256"],
                "offset_seconds": offset,
                "captured_at": frame["captured_at"],
                "detection_status": "detected"
                if detected
                else "failed"
                if status
                else "not_run",
                "candidates": [dict(a, box=_box(a.get("box"))) for a in animals],
            }
        )
        links.append(f'<a href="#frame-{index}">Inspect {offset:.3f}s</a>')
        cards.append(
            f'<article id="frame-{index}" data-frame="{index}">'
            f"<h2>Frame {index + 1} · {offset:.3f}s</h2><figure>"
            f'<img src="{path}" alt="Sampled frame at {offset:.3f} seconds">'
            '<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" '
            'role="img" aria-label="Predicted candidate regions">'
            + "".join(boxes)
            + "</svg></figure>"
            f"<p>{html.escape(label)}</p><p>"
            f"{html.escape(frame['captured_at'] or 'Capture time unknown')}</p>"
            f'<a href="{path}" target="_blank" rel="noopener">Open original frame</a>'
            '<ol class="regions">' + "".join(regions) + "</ol>"
            "<fieldset><legend>Provisional frame review</legend>"
            '<label>Scene type<select data-field="scene">'
            '<option value="unreviewed">Not reviewed</option>'
            '<option value="slate">Credits / slate</option>'
            '<option value="aerial">Aerial view</option>'
            '<option value="close">Closer view</option>'
            '<option value="other">Other / uncertain</option></select></label>'
            '<label>Any visible animals?<select data-field="presence">'
            '<option value="unreviewed">Not reviewed</option>'
            '<option value="yes">Yes</option><option value="no">No</option>'
            '<option value="uncertain">Uncertain</option></select></label>'
            "<label>Missed visible animals (leave blank if unknown)"
            '<input data-field="missed" type="number" min="0" max="10000" step="1">'
            '</label><label>Review note<textarea data-field="note" maxlength="2000">'
            "</textarea></label></fieldset></article>"
        )
    payload = {
        "schema_version": 1,
        "manifest_sha256": manifest_hash,
        "predictions_sha256": _fingerprint(results),
        "evidence_kind": manifest["metadata"]["evidence_kind"],
        "source_sha256": manifest["source"]["sha256"],
        "frames": records,
    }
    data = (
        json.dumps(payload)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    page = """<!doctype html><meta charset="utf-8"><title>Drone video evidence review</title>
<style>
body{font:16px system-ui;max-width:1100px;margin:24px auto;padding:16px;
background:#f4f7fa;color:#142837}h2{font-size:20px}p,li{overflow-wrap:anywhere}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:20px}
article{background:white;padding:16px;border-radius:12px;scroll-margin-top:16px}
figure{position:relative;margin:0}figure img{width:100%;display:block}
svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
rect{fill:none;stroke:#00ffd0;stroke-width:3;vector-effect:non-scaling-stroke}
text{font:bold 30px system-ui;fill:#00ffd0;stroke:#001c20;stroke-width:5px;paint-order:stroke}
label{display:block;margin:12px 0}input,select,textarea,button{font:inherit;max-width:100%;
padding:8px;box-sizing:border-box}label>select,label>input,label>textarea{display:block;width:100%}
fieldset{border:1px solid #bdcdd6;border-radius:8px}textarea{min-height:64px}
.notice{background:#e3f1f6;padding:16px;border-radius:10px}nav{display:flex;flex-wrap:wrap;gap:12px;
margin:16px 0}.regions{padding-left:24px}#export-json{width:100%;min-height:180px}
@media(max-width:480px){.grid{grid-template-columns:1fr}}
</style><h1>Drone video evidence review</h1>"""
    page += (
        "<p>"
        + html.escape(
            manifest["metadata"]["evidence_kind"] + " · " + manifest["metadata"]["source"]
        )
        + "</p>"
    )
    page += (
        "<p>Credit / permission: " + html.escape(manifest["metadata"]["rights_note"]) + "</p>"
    )
    page += """<div class="notice">Local evidence only. No rescue case created.
Locations unknown.
Sparse samples do not establish absence of animals or injury.
Numbered boxes are model proposals,
not individual animal counts. Group / colony boxes may contain many animals.
<p>Reviews are provisional and model-visible, not independent expert injury labels.
Edits are saved only in this browser when storage is available.
Export JSON to retain/share them;
nothing is saved to the GCP server and this page does not send rescue notifications.</p>
<label>Reviewer name<input id="reviewer" maxlength="80"></label>
<button id="export">Export review JSON</button><p id="review-status" role="status"></p>
<details><summary>Review JSON preview</summary>
<textarea id="export-json" aria-label="Review JSON export" readonly>
</textarea></details></div>"""
    if manifest["sample_limit_reached"]:
        page += "<p>Frame limit reached; this may not cover the entire clip.</p>"
    page += '<nav aria-label="Inspect frame">' + "".join(links) + '</nav><div class="grid">'
    page += "".join(cards) + '</div><script type="application/json" id="review-data">'
    page += data + '</script><script src="review.js" defer></script>'
    (root / "review.html").write_text(page)
    (root / "review.js").write_text(Path(__file__).with_name("video_review.js").read_text())
