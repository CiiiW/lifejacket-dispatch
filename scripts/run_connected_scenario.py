#!/usr/bin/env python3
"""Run one fictional rescue through the real API in a disposable child process.

No server is exposed. Synthetic identity/intake adapters are installed only in
the child process and cannot be selected by the production app's configuration.
"""

import argparse
import html
import json
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "https://securetoken.google.com/lifejacket-connected-scenario"


def worker(directory, output):
    directory = Path(directory).resolve()
    marker = directory / "scenario.marker"
    nonce = os.environ.get("LIFEJACKET_SCENARIO_NONCE")
    if not nonce or not marker.is_file() or marker.read_text() != nonce:
        raise RuntimeError("Use the public command, not the internal worker option")
    database = directory / "scenario.sqlite"
    if database.exists():
        raise RuntimeError("Scenario requires a new disposable database")
    os.environ.update(
        DATABASE_URL="sqlite:///" + database.as_posix(),
        PHOTO_STORAGE_DIR=str(directory / "photos"),
        NETWORK_AUTH_ENABLED="true",
        NETWORK_CASE_ACTIONS_ENABLED="true",
        REPORTER_PHONE_ENABLED="true",
        FIREBASE_AUTH_PROJECT_ID="lifejacket-connected-scenario",
        GCP_PROJECT="lifejacket-connected-scenario",
    )
    sys.path.insert(0, str(ROOT / "backend"))
    from pydantic_settings import BaseSettings

    original_init = BaseSettings.__init__

    def settings_without_dotenv(self, *args, **kwargs):
        kwargs["_env_file"] = None
        original_init(self, *args, **kwargs)

    with patch.object(BaseSettings, "__init__", settings_without_dotenv):
        from lifejacket.config import settings

    if settings.database_url != "sqlite:///" + database.as_posix():
        raise RuntimeError("Refusing any database outside the disposable scenario")

    from fastapi.testclient import TestClient
    from lifejacket.access import dependencies
    from lifejacket.access.identity import InvalidIdentity, VerifiedIdentity
    from lifejacket.access.memberships import (
        approve_membership,
        approve_organization,
        revoke_membership,
    )
    from lifejacket.api.main import app
    from lifejacket.api.routes import reporter_phone
    from lifejacket.models import repository
    from lifejacket.models.db import SessionLocal, engine
    from lifejacket.models.schemas import ConversationStage
    from lifejacket.models.tables import (
        NetworkCaseAssigneeRow,
        NetworkCaseOrganizationRow,
        NetworkCaseRow,
        NetworkResponseEventRow,
    )
    from sqlalchemy import select

    traces = []
    receipts = []

    def verify(token, project):
        if project != "lifejacket-connected-scenario" or token not in {
            "scenario-reporter",
            "scenario-unrelated",
            "scenario-a",
            "scenario-b",
            "scenario-rescuer-b",
            "scenario-noaa",
        }:
            raise InvalidIdentity("Unknown fictional identity")
        phone = token in {"scenario-reporter", "scenario-unrelated"}
        return VerifiedIdentity(
            ISSUER,
            token,
            email=None if phone else token + "@example.invalid",
            email_verified=not phone,
            phone_number="+12025550123" if phone else None,
            sign_in_provider="phone" if phone else "password",
            auth_time=int(datetime.now(UTC).timestamp()),
        )

    def headers(person, organization=None):
        return {"Authorization": "Bearer scenario-" + person} | (
            {"X-LifeJacket-Organization": organization} if organization else {}
        )

    def check(name, response, expected=200, *, role="scenario", phase=None):
        if response.status_code != expected:
            raise AssertionError(
                f"{name}: expected HTTP {expected}, got {response.status_code}"
            )
        traces.append(
            {
                "step": name,
                "role": role,
                "http_status": expected,
                "phase": phase,
                "passed": True,
            }
        )
        return response.json()

    # All actual HTTP calls below are in-process ASGI TestClient requests.
    # Any accidental external socket use fails rather than contacting a provider.
    with (
        patch.object(dependencies, "verify_provider_token", verify),
        patch.object(reporter_phone, "verify_provider_token", verify),
        patch(
            "socket.socket.connect",
            side_effect=RuntimeError("Scenario networking is disabled"),
        ),
        patch(
            "socket.create_connection",
            side_effect=RuntimeError("Scenario networking is disabled"),
        ),
        TestClient(app) as client,
    ):
        check(
            "Unknown fictional token is denied",
            client.get("/access/me", headers={"Authorization": "Bearer unknown-token"}),
            401,
        )
        people = {}
        for person in ["a", "b", "rescuer-b", "noaa"]:
            profile = check(
                "Create fictional personal identity",
                client.get("/access/me", headers=headers(person)),
                role=person,
            )
            if profile["role"] != "reporter" or profile["organizations"]:
                raise AssertionError("Signing in must not auto-grant professional access")
            people[person] = profile["account_id"]
        with SessionLocal() as session:
            for org, name, kind, states in [
                ("A", "Fictional Coast Center A", "rescue_center", ["CA"]),
                ("B", "Fictional Coast Center B", "rescue_center", ["CA"]),
                ("NOAA", "Fictional NOAA Review", "noaa", []),
            ]:
                approve_organization(session, org, name, kind, states, "scenario-admin")
            memberships = {}
            for person, org, role, states in [
                ("a", "A", "center_coordinator", ["CA"]),
                ("b", "B", "center_coordinator", ["CA"]),
                ("rescuer-b", "B", "rescuer", ["CA"]),
                ("noaa", "NOAA", "noaa", []),
            ]:
                memberships[person] = approve_membership(
                    session, people[person], org, role, states, "scenario-admin"
                ).membership_id

        draft = check(
            "Reporter starts private draft", client.post("/reporter/drafts"), role="reporter"
        )
        case_id = draft["turn"]["incident_id"]
        submission = {
            "draft_key": draft["draft_key"],
            "id_token": "scenario-reporter",
            "contact_channels": ["text"],
        }
        check(
            "Incomplete draft cannot be submitted",
            client.post(f"/reporter/drafts/{case_id}/submit", json=submission),
            409,
            role="reporter",
        )
        with SessionLocal() as session:
            state = repository.load_conversation_state(session, case_id)
            state.stage = ConversationStage.COMPLETE
            repository.save_conversation_state(session, case_id, state)
            session.commit()
        check(
            "Phone-verified reporter explicitly submits",
            client.post(f"/reporter/drafts/{case_id}/submit", json=submission),
            role="reporter",
            phase="received",
        )
        received = check(
            "Reporter sees received before any team acceptance",
            client.post(
                f"/reporter/reports/{case_id}/status", json={"id_token": "scenario-reporter"}
            ),
            role="reporter",
            phase="received",
        )
        if received["phase"] != "received" or received["arrival_eta_minutes"] is not None:
            raise AssertionError("Submission must not imply a team is already travelling")
        receipts.append(
            {"phase": "received", "message": received["message"], "eta_minutes": None}
        )
        check(
            "Unrelated reporter cannot read the case",
            client.post(
                f"/reporter/reports/{case_id}/status", json={"id_token": "scenario-unrelated"}
            ),
            404,
            role="unrelated",
        )
        check("Legacy incident path remains blocked", client.get(f"/incidents/{case_id}"), 403)

        # Trusted fixture provisioning, not a claimed production review/invitation UI.
        with SessionLocal() as session:
            scope = session.get(NetworkCaseRow, case_id)
            scope.state_code = "CA"
            scope.verified_at = datetime.now(UTC).replace(tzinfo=None)
            scope.verified_by = "scenario-admin"
            scope.lead_org_id = "A"
            session.commit()
        for person, org in [("a", "A"), ("b", "B"), ("noaa", "NOAA")]:
            cards = check(
                "Permitted organization discovers the same submitted case",
                client.get("/network/cases", headers=headers(person, org)),
                role=person,
            )
            if [row["incident_id"] for row in cards] != [case_id]:
                raise AssertionError("Role views must refer to the same submitted case")
        contact_path = f"/network/cases/{case_id}/reporter-contact"
        response_path = f"/network/cases/{case_id}/response"
        for person, org in [("b", "B"), ("noaa", "NOAA")]:
            check(
                "Case discovery does not grant reporter contact",
                client.get(contact_path, headers=headers(person, org)),
                403,
                role=person,
            )
            check(
                "Case discovery does not grant response changes",
                client.patch(
                    response_path,
                    headers=headers(person, org),
                    json={"revision": 0, "phase": "accepted", "confirmed": True},
                ),
                403,
                role=person,
            )
        check(
            "Unassigned rescuer cannot read operations",
            client.get(response_path, headers=headers("rescuer-b", "B")),
            404,
            role="rescuer-b",
        )

        with SessionLocal() as session:
            session.add(
                NetworkCaseOrganizationRow(
                    incident_id=case_id, organization_id="B", kind="supporting", accepted=True
                )
            )
            session.add(
                NetworkCaseAssigneeRow(
                    incident_id=case_id,
                    organization_id="B",
                    user_id=people["rescuer-b"],
                    accepted=True,
                )
            )
            session.commit()
        contact = check(
            "Accepted assigned support gets text-only contact",
            client.get(contact_path, headers=headers("rescuer-b", "B")),
            role="rescuer-b",
        )
        if contact["channels"] != ["text"]:
            raise AssertionError("Only the reporter's selected channel may be returned")
        check(
            "Reporter leaves without cancellation",
            client.post(
                f"/reporter/reports/{case_id}/presence",
                json={"id_token": "scenario-reporter", "presence": "left"},
            ),
            role="reporter",
        )
        check(
            "Reporter withdraws current-case contact",
            client.post(
                f"/reporter/reports/{case_id}/contact-preferences",
                json={"id_token": "scenario-reporter", "contact_channels": []},
            ),
            role="reporter",
        )
        check(
            "Withdrawal immediately denies staff contact",
            client.get(contact_path, headers=headers("rescuer-b", "B")),
            403,
            role="rescuer-b",
        )

        for revision, phase in enumerate(
            ["accepted", "en_route", "on_scene", "animal_located", "closed"], start=1
        ):
            person, org = ("a", "A") if phase == "closed" else ("rescuer-b", "B")
            body = {"revision": revision - 1, "phase": phase, "confirmed": True}
            if phase == "closed":
                check(
                    "Supporting center cannot close the lead case",
                    client.patch(
                        response_path,
                        headers=headers("b", "B"),
                        json=body | {"closure_reason": "rescue_complete"},
                    ),
                    409,
                    role="b",
                )
                body["closure_reason"] = "rescue_complete"
            saved = check(
                "Human-confirmed response: " + phase,
                client.patch(response_path, headers=headers(person, org), json=body),
                role=person,
                phase=phase,
            )
            if saved["revision"] != revision:
                raise AssertionError("Expected monotonic revision")
            if phase == "accepted":
                check(
                    "Stale update cannot overwrite a newer response",
                    client.patch(
                        response_path,
                        headers=headers("rescuer-b", "B"),
                        json={"revision": 0, "phase": "en_route", "confirmed": True},
                    ),
                    409,
                    role="rescuer-b",
                )
            own = check(
                "Reporter sees the same confirmed response",
                client.post(
                    f"/reporter/reports/{case_id}/status",
                    json={"id_token": "scenario-reporter"},
                ),
                role="reporter",
                phase=phase,
            )
            if (
                own["phase"] != phase
                or own["arrival_eta_minutes"] is not None
                or own["presence"] != "left"
            ):
                raise AssertionError(
                    "Reporter status must match the event, omit unavailable ETA "
                    "and preserve departure availability"
                )
            allowed = {
                "case_id",
                "phase",
                "message",
                "arrival_eta_minutes",
                "eta_updated_at",
                "eta_basis",
                "eta_is_estimate",
                "reporter_can_leave",
                "leaving_cancels_report",
                "presence",
            }
            if set(own) != allowed:
                raise AssertionError("Unexpected reporter data exposure")
            receipts.append({"phase": phase, "message": own["message"], "eta_minutes": None})
            noaa = check(
                "NOAA sees the same response without operational permission",
                client.get(response_path, headers=headers("noaa", "NOAA")),
                role="noaa",
                phase=phase,
            )
            if (
                noaa["phase"] != phase
                or noaa["allowed_transitions"]
                or noaa["contact_channels"]
            ):
                raise AssertionError("NOAA must remain read-only in this workflow")
        with SessionLocal() as session:
            events = session.scalars(
                select(NetworkResponseEventRow)
                .where(NetworkResponseEventRow.incident_id == case_id)
                .order_by(NetworkResponseEventRow.revision)
            ).all()
            if [event.phase for event in events] != [
                r["phase"] for r in receipts if r["phase"] != "received"
            ]:
                raise AssertionError("Response audit does not match the API lifecycle")
            revoke_membership(session, memberships["rescuer-b"], "scenario-admin")
        check(
            "Revoked member cannot continue using selected organization",
            client.get(response_path, headers=headers("rescuer-b", "B")),
            403,
            role="rescuer-b",
        )
        check(
            "Closed case no longer exposes reporter contact",
            client.get(contact_path, headers=headers("a", "A")),
            403,
            role="a",
        )
    engine.dispose()
    output.mkdir(parents=True, exist_ok=True)
    (output / "latest.json").write_text(
        json.dumps(
            {
                "mode": "isolated-connected-scenario",
                "passed": True,
                "generated_at": datetime.now(UTC).isoformat(),
                "checks": traces,
                "reporter_timeline": receipts,
                "boundaries": [
                    "Phone identities and completed intake are fictional test adapters.",
                    "Organization approval, case review, support acceptance and assignment "
                    "are trusted fixture setup; production workflows remain incomplete.",
                    "API routes, membership checks, state changes and reporter projections "
                    "use real code sharing one temporary database.",
                    "No public server, real SMS, model calls, notifications "
                    "or live rescue case.",
                ],
            },
            indent=2,
        )
    )


def render(result):
    rows = "".join(
        "<tr><td>"
        + str(index)
        + "</td><td>"
        + html.escape(item["role"])
        + "</td><td>"
        + html.escape(item["step"])
        + "</td><td>"
        + str(item["http_status"])
        + "</td><td>Passed</td></tr>"
        for index, item in enumerate(result["checks"], 1)
    )
    timeline = "".join(
        "<li><strong>"
        + html.escape(item["phase"].replace("_", " "))
        + "</strong> — "
        + html.escape(item["message"])
        + "</li>"
        for item in result["reporter_timeline"]
    )
    bounds = "".join("<li>" + html.escape(item) + "</li>" for item in result["boundaries"])
    styles = """
body{margin:0;background:#0b132b;color:#f4f7fb;font:16px/1.6 system-ui}
main{max-width:1050px;margin:auto;padding:28px}
h1{font-size:30px}h2{font-size:22px}.good{color:#48cae4}
.card{background:#101a38;border:1px solid #ffffff25;border-radius:14px;
padding:24px;margin:20px 0}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border-bottom:1px solid #ffffff25;text-align:left;padding:10px}
small{color:#b1bdd1}
@media(max-width:600px){main{padding:16px}.card{padding:14px}table{font-size:12px}}
"""
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LifeJacket connected scenario</title><style>{styles}</style></head>
<body><main>
<small>LifeJacket · Isolated API scenario · Fictional identities and intake</small>
<h1>One case, connected across roles.</h1>
<p class="good">{len(result["checks"])} checks passed · One isolated DB
· No GCP or real SMS</p>
<small>Completed run: {html.escape(result["generated_at"])}</small>
<section class="card"><h2>Reporter → Center A → Center B → NOAA</h2>
<p>The reporter submits a private case. Center A leads; an accepted Center B
rescuer confirms response events. NOAA reads the same case.
The reporter sees only permitted updates.</p>
<p>Disposable database removed after the run:
<strong>{result["temporary_database_removed"]}</strong></p></section>
<section class="card"><h2>What the reporter saw</h2><ol>{timeline}</ol>
<p>Arrival estimate unavailable throughout.
Leaving and withdrawing contact did not cancel the case.</p></section>
<section class="card"><h2>What this proves—and what it simulates</h2>
<ul>{bounds}</ul></section>
<section class="card"><h2>Recorded API checks</h2><table><thead><tr>
<th>#</th><th>Role</th><th>Check</th><th>HTTP</th><th>Result</th>
</tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "var/connected-workflow")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if args.worker:
        worker(args.worker, output)
        return
    with tempfile.TemporaryDirectory(prefix="lifejacket-connected-") as folder:
        directory = Path(folder)
        nonce = secrets.token_hex(24)
        (directory / "scenario.marker").write_text(nonce)
        env = os.environ.copy()
        env["LIFEJACKET_SCENARIO_NONCE"] = nonce
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(directory),
                "--output-dir",
                str(output),
            ],
            env=env,
            cwd=directory,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            print(
                "Connected scenario failed. No production database was used.", file=sys.stderr
            )
            print(result.stderr, file=sys.stderr)
            raise SystemExit(result.returncode)
    report = json.loads((output / "latest.json").read_text())
    report["temporary_database_removed"] = not directory.exists()
    (output / "latest.json").write_text(json.dumps(report, indent=2))
    (output / "latest.html").write_text(render(report))
    print(
        f"Connected scenario passed: {len(report['checks'])} API checks. "
        "Temporary database removed."
    )
    print(f"Open {output / 'latest.html'} or restart npm run demo:network for /connected/.")


if __name__ == "__main__":
    main()
