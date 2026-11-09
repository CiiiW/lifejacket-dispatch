"""Drone phase for the isolated connected API runner; never imported by the app."""

import base64
import copy
import hashlib
import html
import io
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def prepare_intake(session, case_id):
    """Prepared intake fixture, explicitly separate from live AI/photo evaluation."""
    from lifejacket.models.schemas import (
        AnimalGroup,
        AssessmentResult,
        IdentificationResult,
        IncidentReport,
        InjuryAssessment,
        SeverityLevel,
        SpeciesCandidate,
    )
    from lifejacket.models.tables import IncidentRow

    row = session.get(IncidentRow, case_id)
    identification = IdentificationResult(
        candidates=[
            SpeciesCandidate(
                common_name="Fictional possible seal",
                confidence=0.62,
                animal_group=AnimalGroup.PINNIPED,
            ),
        ]
    )
    assessment = AssessmentResult(
        animal_group=AnimalGroup.PINNIPED,
        injury=InjuryAssessment(confidence=0.58),
        severity_level=SeverityLevel.MONITOR,
        recommended_action="Coordinator reviews the fictional evidence gap.",
    )
    row.status = "awaiting_dispatch"
    row.latitude, row.longitude = 36.8, -121.79
    row.animal_group = "pinniped"
    row.species_common_name = "Fictional possible seal"
    row.species_confidence = 0.62
    row.taxon_rank = "group"
    row.severity_level = "monitor"
    row.identification_json = identification.model_dump(mode="json")
    row.assessment_json = assessment.model_dump(mode="json")
    row.report_json = IncidentReport(
        headline="Fictional animal needs coordinator review",
        summary="Prepared intake fixture; no live model or wildlife evidence.",
        unknowns=["Animal group and condition require more evidence."],
    ).model_dump(mode="json")
    session.flush()


def run_drone_checks(client, case_id, headers, check, sessions):
    from lifejacket.models.tables import (
        CaseDroneEventRow,
        CaseDroneEvidenceRow,
        CaseDroneRequestRow,
        IncidentRow,
        NetworkCaseRow,
    )
    from PIL import Image, ImageDraw
    from sqlalchemy import select

    path = f"/network/cases/{case_id}/drone-requests"
    lead = headers("a", "A")
    with sessions() as session:
        incident = session.get(IncidentRow, case_id)
        before = copy.deepcopy(incident.assessment_json)
        before_report = copy.deepcopy(incident.report_json)
        phase = session.get(NetworkCaseRow, case_id).response_phase
        if session.scalars(select(CaseDroneRequestRow)).all():
            raise AssertionError("Drone scenario must start without requests")

    check("Anonymous cannot read drone requests", client.get(path), 401)
    check(
        "Reporter cannot read internal drone requests",
        client.get(path, headers=headers("reporter")),
        404,
        role="reporter",
    )
    for person, org in [("b", "B"), ("noaa", "NOAA")]:
        check(
            "Case visibility does not grant drone operations",
            client.get(path, headers=headers(person, org)),
            403,
            role=person,
        )

    initial = check(
        "Lead sees automatic confidence suggestion on the submitted case",
        client.get(path, headers=lead),
        role="a",
    )
    if not initial["can_create"] or initial["requests"] or len(initial["suggestions"]) != 1:
        raise AssertionError("Expected one read-only automatic suggestion")
    suggestion = initial["suggestions"][0]
    if {s["code"] for s in suggestion["signals"]} != {
        "animal_group_uncertain",
        "condition_uncertain",
    }:
        raise AssertionError("Prepared confidence signals did not reach the actual API")

    body = {
        "purpose": "verification",
        "objective": suggestion["objective"],
        "reason": suggestion["reason"],
        "execution_kind": "recorded_demo",
        "escalation_criteria": suggestion["escalation_criteria"],
        "request_key": "connected-drone-request",
        "suggestion_id": suggestion["suggestion_id"],
    }
    check(
        "Another center cannot create a request on the lead case",
        client.post(path, headers=headers("b", "B"), json=body),
        403,
        role="b",
    )
    created = check(
        "Coordinator explicitly creates the suggested request",
        client.post(path, headers=lead, json=body),
        201,
        role="a",
    )
    request_id = created["request_id"]
    detail_path = path + "/" + request_id
    if created["case_id"] != case_id or created["status"] != "requested":
        raise AssertionError("Creation must stay attached to the same case and unapproved")
    retry = check(
        "Retry reuses the same request",
        client.post(path, headers=lead, json=body),
        201,
        role="a",
    )
    if retry["request_id"] != request_id:
        raise AssertionError("Retry created a duplicate request")

    def update(state, status, **extra):
        return client.patch(
            detail_path,
            headers=lead,
            json={
                "revision": state["revision"],
                "status": status,
                "confirmed": True,
                "note": "Fictional connected scenario: " + status,
                **extra,
            },
        )

    check(
        "Collection cannot start before approval",
        update(created, "in_progress"),
        409,
        role="a",
    )
    check(
        "Approval requires a responsible operator", update(created, "approved"), 422, role="a"
    )
    approved = check(
        "Lead approves sample-footage review",
        update(created, "approved", operator="Fictional footage reviewer"),
        role="a",
    )
    check(
        "A stale revision cannot start collection",
        update(created, "in_progress"),
        409,
        role="a",
    )
    running = check(
        "Approved request enters evidence collection",
        update(approved, "in_progress"),
        role="a",
    )
    check(
        "Evidence-ready requires attached evidence",
        update(running, "evidence_ready"),
        409,
        role="a",
    )

    image = Image.new("RGB", (480, 240), "#17364a")
    draw = ImageDraw.Draw(image)
    draw.rectangle((28, 26, 452, 214), outline="#48cae4", width=3)
    draw.text((48, 88), "SYNTHETIC WORKFLOW FRAME", fill="white")
    draw.text((48, 116), "No animal or flight evidence", fill="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    metadata = {
        "revision": running["revision"],
        "source_kind": "sample_footage",
        "source_url": "https://example.invalid/synthetic-connected-frame",
        "rights_note": "Generated test pattern; no NOAA video or actual animal evidence.",
        "description": "Synthetic frame exercises upload and review only.",
        "captured_at": None,
        "frame_offset_seconds": 0,
        "animal_latitude": None,
        "animal_longitude": None,
    }

    def upload(meta):
        return client.post(
            detail_path + "/evidence",
            headers=lead,
            data={"metadata": json.dumps(meta)},
            files={"photo": ("synthetic-frame.png", data, "image/png")},
        )

    check(
        "Operator footage cannot be mislabeled as recorded demo evidence",
        upload(
            metadata
            | {"source_kind": "operator_capture", "captured_at": datetime.now(UTC).isoformat()}
        ),
        422,
        role="a",
    )
    uploaded = check(
        "Synthetic frame attaches to the approved case request",
        upload(metadata),
        201,
        role="a",
    )
    check("Stale upload cannot duplicate the frame", upload(metadata), 409, role="a")
    photo_path = detail_path + "/evidence/" + uploaded["evidence_id"] + "/photo"
    downloaded = check(
        "Authorized evidence download matches the original bytes",
        client.get(photo_path, headers=lead),
        role="a",
        raw=True,
    )
    if downloaded != data:
        raise AssertionError("Evidence bytes changed on round trip")
    check(
        "Reporter cannot download internal evidence",
        client.get(photo_path, headers=headers("reporter")),
        404,
        role="reporter",
    )
    check(
        "Another case cannot reference this evidence",
        client.get(photo_path.replace(case_id, "different-case"), headers=lead),
        404,
        role="a",
    )
    running["revision"] = uploaded["revision"]
    ready = check(
        "Coordinator submits evidence for review", update(running, "evidence_ready"), role="a"
    )
    check(
        "Review requires an explicit evidence outcome",
        update(ready, "reviewed"),
        422,
        role="a",
    )
    finding = (
        "The synthetic frame cannot establish animal movement. "
        "Further observation and coordinator review are needed."
    )
    reviewed = check(
        "Coordinator records uncertainty and a follow-up time",
        update(
            ready,
            "reviewed",
            outcome="still_uncertain",
            note=finding,
            next_review_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        ),
        role="a",
    )
    saved = check(
        "Same case returns the evidence and saved reassessment",
        client.get(detail_path, headers=lead),
        role="a",
    )
    if saved["case_id"] != case_id or saved["request_id"] != request_id:
        raise AssertionError("Reassessment linked to a different case/request")
    if saved["outcome"] != "still_uncertain" or saved["review_note"] != finding:
        raise AssertionError("Review finding was not persisted")
    if (
        len(saved["evidence"]) != 1
        or saved["evidence"][0]["sha256"] != digest
        or saved["evidence"][0]["captured_at"] is not None
        or saved["evidence"][0]["animal_latitude"] is not None
    ):
        raise AssertionError("Evidence integrity or unknown source metadata was lost")
    expected_events = [
        "requested",
        "approved",
        "in_progress",
        "evidence_attached",
        "evidence_ready",
        "reviewed",
    ]
    if [e["kind"] for e in saved["events"]] != expected_events:
        raise AssertionError("Request audit does not match actual API changes")
    if [e["revision"] for e in saved["events"]] != list(range(6)):
        raise AssertionError("Request audit revisions are not monotonic")
    with sessions() as session:
        incident = session.get(IncidentRow, case_id)
        if incident.assessment_json != before or incident.report_json != before_report:
            raise AssertionError("Drone review overwrote the original intake")
        if session.get(NetworkCaseRow, case_id).response_phase != phase:
            raise AssertionError("Drone review advanced the rescue response")
        requests = session.scalars(select(CaseDroneRequestRow)).all()
        evidence = session.scalars(select(CaseDroneEvidenceRow)).all()
        events = session.scalars(select(CaseDroneEventRow)).all()
        if len(requests) != 1 or len(evidence) != 1 or len(events) != 6:
            raise AssertionError("Expected one request, one frame, six audit events")
        if evidence[0].request_id != request_id or requests[0].incident_id != case_id:
            raise AssertionError("Database linkage is inconsistent")

    projected = check(
        "Reporter still sees only the confirmed rescue response",
        client.post(
            f"/reporter/reports/{case_id}/status", json={"id_token": "scenario-reporter"}
        ),
        role="reporter",
    )
    if projected["phase"] != phase or any(k.startswith("drone") for k in projected):
        raise AssertionError("Internal drone workflow leaked into reporter status")
    remaining = check(
        "Sample review leaves the operational suggestion available",
        client.get(path, headers=lead),
        role="a",
    )
    if len(remaining["suggestions"]) != 1:
        raise AssertionError("Sample evidence incorrectly consumed operational uncertainty")

    return {
        "case_reference": "CASE-01",
        "request_reference": "DRONE-01",
        "status": reviewed["status"],
        "outcome": saved["outcome"],
        "finding": finding,
        "purpose": "verification",
        "execution_kind": "recorded_demo",
        "initial_confidence": initial["confidence_summary"],
        "threshold": suggestion["threshold"],
        "source_kind": "sample_footage",
        "source_is_synthetic": True,
        "capture_time": None,
        "animal_coordinates": None,
        "evidence_sha256": digest,
        "frame_base64": base64.b64encode(data).decode("ascii"),
        "timeline": [{"event": e["kind"], "revision": e["revision"]} for e in saved["events"]],
        "same_case_verified": True,
        "original_intake_preserved": True,
        "rescue_phase_preserved_during_drone_review": phase,
        "operational_suggestion_preserved": True,
        "next_review_at": saved["next_review_at"],
    }


def render_drone(result):
    drone = result["drone_workflow"]
    completed = (
        datetime.fromisoformat(result["generated_at"])
        .astimezone(ZoneInfo("America/Chicago"))
        .strftime("%b %d, %Y · %I:%M %p %Z")
    )
    rows = "".join(
        "<tr><td>"
        + str(i)
        + "</td><td>"
        + html.escape(r["role"])
        + "</td><td>"
        + html.escape(r["step"])
        + "</td><td>"
        + str(r["http_status"])
        + "</td><td>Passed</td></tr>"
        for i, r in enumerate(result["checks"], 1)
    )
    timeline = "".join(
        "<li><strong>"
        + html.escape(item["event"].replace("_", " "))
        + "</strong><small>revision "
        + str(item["revision"])
        + "</small></li>"
        for item in drone["timeline"]
    )
    bounds = "".join("<li>" + html.escape(b) + "</li>" for b in result["boundaries"])
    return f"""<!doctype html><html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LifeJacket connected drone scenario</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;
background:#0b132b;
color:#f4f7fb;
font:16px/1.6 system-ui}}

main{{max-width:1100px;
margin:auto;
padding:30px}}
h1{{font-size:32px;
line-height:1.2;
margin:12px 0}}

h2{{font-size:21px}}
.eyebrow,.good{{color:#48cae4}}
.eyebrow{{font-size:12px;
letter-spacing:1.5px}}

.card{{padding:24px;
margin:20px 0;
background:#101a38;
border:1px solid #ffffff25;
border-radius:14px}}

.grid{{display:grid;
grid-template-columns:1fr 1fr;
gap:20px}}
small{{display:block;
color:#a9b4c6}}

.timeline{{padding:0;
display:grid;
grid-template-columns:repeat(3,1fr);
gap:12px;
list-style:none}}

.timeline li{{border-left:3px solid #48cae4;
padding:12px;
background:#ffffff05}}

.finding{{border-left:3px solid #48cae4;
padding-left:16px}}

img{{max-width:100%;
border-radius:8px}}
table{{border-collapse:collapse;
width:100%;
font-size:13px}}

td,th{{padding:10px;
text-align:left;
border-bottom:1px solid #ffffff25}}

summary{{cursor:pointer}}
@media(max-width:700px){{main{{padding:16px}}
.grid{{grid-template-columns:1fr}}

.timeline{{grid-template-columns:1fr 1fr}}
.card{{padding:16px}}
}}

</style>
</head>
<body>
<main>
<div class="eyebrow">LIFEJACKET · CONNECTED BACKEND CHECK</div>
<h1>One reported case. One reviewed drone request.</h1>
<p class="good">{len(result["checks"])} API checks passed
· Same temporary database</p>
<small>Completed run: {html.escape(completed)}. This page displays saved results.</small>
<section class="card">
<h2>Reporter submission → confidence suggestion → evidence review</h2>
<p>CASE-01 was submitted through the reporter API, reviewed for Center A,
and used throughout the drone request and evidence routes.</p>
<ul class="timeline">{timeline}</ul>
<p>Animal-group confidence:
<strong>{round(drone["initial_confidence"]["animal_group"] * 100)}%</strong>
 · condition confidence:
<strong>{round(drone["initial_confidence"]["condition"] * 100)}%</strong>

· provisional suggestion threshold:
<strong>{round(drone["threshold"] * 100)}%</strong>
.</p>
</section>
<div class="grid">
<section class="card">
<h2>Evidence returned to CASE-01</h2>
<img src="data:image/png;base64,{drone["frame_base64"]}"
 alt="Synthetic workflow test pattern, not wildlife evidence">
<small>One generated PNG. Capture time and animal coordinates remain unknown.
No NOAA footage, actual aircraft or wildlife recognition was tested.</small>
</section>
<section class="card">
<h2>Review outcome: still uncertain</h2>
<p class="finding">{html.escape(drone["finding"])}</p>
<p>Saved as a case addendum. Original intake preserved;
 rescue status stayed
<strong>{html.escape(drone["rescue_phase_preserved_during_drone_review"])}</strong>

during drone review.</p>
<small>The later fictional field-response steps closed the case separately.
The sample frame did not confirm a rescue or resolve operational uncertainty.</small>
</section>
</div>
<section class="card">
<h2>Verified boundaries</h2>
<ul>
<li>One case, one request, one frame and six versioned request events.</li>
<li>Approval, evidence submission and review are separate steps.</li>
<li>Reporter, unrelated-center, stale-write and cross-case access checks passed.</li>
<li>Sample review leaves the operational suggestion available.</li>
<li>Temporary database and evidence removed:
<strong>{result["temporary_database_removed"]}</strong>
.</li>
</ul>
<details>
<summary>Simulation and evidence limits</summary>
<ul>{bounds}</ul>
</details>
</section>
<section class="card">
<details>
<summary>Inspect all {len(result["checks"])} API checks</summary>
<table>
<thead>
<tr>
<th>#</th>
<th>Role</th>
<th>Check</th>
<th>HTTP</th>
<th>Result</th>
</tr>
</thead>
<tbody>{rows}</tbody>
</table>
</details>
</section>
</main>
</body>
</html>"""
