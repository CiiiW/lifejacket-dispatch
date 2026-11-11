"""Build the README's editable SVG diagrams using only the Python standard library."""

# ruff: noqa: E501 -- SVG attributes and diagram labels stay readable as units.

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)
NAVY, PANEL, LINE, INK, MUTED, TEAL, GOLD = (
    "#FFFFFF",
    "#F1F8F7",
    "#D5DFE5",
    "#202832",
    "#586879",
    "#087F8C",
    "#B66B12",
)


def text(x, y, value, size=20, color=INK, weight=400):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>'


def lines(x, y, values, size=20, color=MUTED):
    return "".join(text(x, y + i * 29, value, size, color) for i, value in enumerate(values))


def box(x, y, w, h, title, body, badge=None, pending=False):
    stroke = GOLD if pending else LINE
    dash = ' stroke-dasharray="7 5"' if pending else ""
    result = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{PANEL}" stroke="{stroke}" stroke-width="1.5"{dash}/>'
    if badge:
        result += text(x + 22, y + 31, badge.upper(), 14, GOLD if pending else TEAL, 700)
    result += text(x + 22, y + (65 if badge else 38), title, 25, INK, 650)
    result += lines(x + 22, y + (101 if badge else 75), body, 19)
    return result


def arrow(points, color=TEAL, dashed=False):
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    return f'<path d="{points}" fill="none" stroke="{color}" stroke-dasharray="5 7" stroke-width="2.5" marker-end="url(#arrow)"{dash}/>'


def save(name, h, title, description, body):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{h}" viewBox="0 0 1200 {h}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10Z" fill="{TEAL}"/></marker></defs>
<rect width="1200" height="{h}" rx="24" fill="{NAVY}"/>
<g font-family="Arial, Helvetica, sans-serif">{body}</g></svg>'''
    (OUT / name).write_text(svg + "\n")


def icon(x, y, kind):
    shapes = {
        "phone": '<rect x="3" y="0" width="20" height="30" rx="4"/><path d="M10 25h6"/>',
        "review": '<path d="M14 0 27 5v10c0 8-7 13-13 17C8 28 1 23 1 15V5Z"/><path d="m7 15 5 5 10-11"/>',
        "camera": '<rect x="0" y="7" width="31" height="22" rx="5"/><path d="m7 7 3-6h11l3 6"/><circle cx="16" cy="18" r="6"/>',
    }
    return f'<g transform="translate({x} {y})" fill="none" stroke="{TEAL}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{shapes[kind]}</g>'


def overview():
    b = text(42, 47, "LIFEJACKET / THE BIG PICTURE", 15, TEAL, 700)
    b += text(42, 95, "Clearer evidence. A shared case. A human decision.", 33, INK, 700)
    b += text(
        42,
        132,
        "A rescue coordination prototype, from the first report to follow-up review.",
        20,
        MUTED,
    )
    b += box(
        42,
        173,
        340,
        191,
        "Report what you see",
        ["Photo + location", "Choose the intended animal", "Answer guided questions"],
        "01 / PUBLIC REPORT",
    )
    b += box(
        430,
        173,
        340,
        191,
        "Review the case",
        ["Structured findings", "Rule-based urgency reasons", "Responder candidates"],
        "02 / COORDINATOR",
    )
    b += box(
        818,
        173,
        340,
        191,
        "Add another view",
        [
            "Approved observation request",
            "Video + saved original frames",
            "Compare and review findings",
        ],
        "03 / OBSERVATION",
    )
    b += icon(337, 190, "phone") + icon(725, 190, "review") + icon(1104, 190, "camera")
    b += arrow("M382 268 H424") + arrow("M770 268 H812")
    b += arrow("M988 364 V414 H600 V370")
    b += text(711, 405, "New evidence returns to the same case", 17, MUTED)
    b += '<rect x="42" y="449" width="1116" height="64" rx="14" fill="#E6F5EF"/>'
    b += text(68, 488, "HUMAN REVIEW", 17, TEAL, 700)
    b += text(
        260,
        488,
        "The coordinator records the next step. Nothing dispatches a rescue automatically.",
        19,
    )
    save(
        "judges-overview.svg",
        544,
        "LifeJacket: report, review, observe",
        "Public reports become structured cases for coordinator review. Optional observation adds evidence back to the same case. Human approval remains central.",
        b,
    )


def architecture():
    b = text(42, 47, "LIFEJACKET / AI, TOOLS AND HUMAN CONTROL", 15, TEAL, 700)
    b += text(42, 95, "Different responsibilities. One reviewable workflow.", 33, INK, 700)
    b += text(
        42,
        132,
        "Model components interpret evidence; rules and people control consequential steps.",
        20,
        MUTED,
    )
    b += '<rect x="42" y="174" width="672" height="348" rx="18" fill="#F4F2FC" stroke="#D5DFE5"/>'
    b += text(65, 211, "ORCHESTRATED MODEL COMPONENTS", 15, TEAL, 700)
    for x, title, subtitle in [
        (64, "Detect", "Locate candidates"),
        (279, "Identify", "Resolve identity"),
        (494, "Assess", "Describe condition"),
    ]:
        b += box(x, 232, 198, 106, title, [subtitle])
    b += text(65, 378, "Cross-check → write report → guardrail check", 22, INK, 650)
    b += lines(
        65,
        417,
        [
            "Code manages the stages, question budgets and fallbacks.",
            "These boxes are specialized tasks, not independent planners.",
        ],
        19,
    )
    b += box(
        752,
        174,
        406,
        170,
        "Coordination agent",
        ["Chooses scoped, read-only tools", "Inspects results in a bounded loop"],
        "TOOL-USING AGENT",
    )
    b += box(
        752,
        379,
        406,
        143,
        "Read-only case tools",
        ["History · assignments · pending tasks", "Available responders"],
        None,
    )
    b += arrow("M955 344 V373")
    b += arrow("M1158 449 H1177 V257 H1164")
    b += arrow("M378 522 V558") + arrow("M955 522 V558")
    b += box(
        42,
        564,
        672,
        146,
        "Deterministic rules + services",
        [
            "Urgency · responder ranking · duplicate checks",
            "Permissions · saved evidence · workflow state",
        ],
        None,
    )
    b += box(
        752,
        564,
        406,
        146,
        "Human coordinator",
        ["Reviews evidence and uncertainty", "Approves the operational next step"],
        None,
    )
    b += arrow("M714 635 H746")
    b += text(
        42,
        752,
        "Architecture overview: the coordination tools do not command the aircraft or dispatch a rescue.",
        18,
        MUTED,
    )
    save(
        "judges-ai-roles.svg",
        790,
        "AI pipeline, coordination agent, rules and coordinator",
        "The code-orchestrated model pipeline is distinct from the bounded read-only tool-using coordination agent. Deterministic services support a human coordinator. This diagram is a responsibility map, not a claim that each component is an autonomous agent.",
        b,
    )


def drone():
    b = text(42, 47, "LIFEJACKET / DRONE EVIDENCE", 15, TEAL, 700)
    b += text(42, 95, "Keep the footage. Analyze selected evidence.", 34, INK, 700)
    b += text(
        42,
        132,
        "Current existing-case review path; physical aircraft connectivity still needs acceptance.",
        20,
        MUTED,
    )
    b += box(
        42,
        174,
        492,
        150,
        "Mini 2 + iPhone / DJI Fly",
        [
            "Pilot publishes video to a private address",
            "Actual phone-to-server link: not yet tested",
        ],
        "HARDWARE ACCEPTANCE PENDING",
        True,
    )
    b += box(
        612,
        174,
        546,
        150,
        "Private stream receiver",
        ["Receives the feed and shows a sampled preview", "No flight-control commands"],
        "SOFTWARE REHEARSED",
    )
    b += arrow("M534 250 H606")
    b += arrow("M780 324 V355 H286 V382") + arrow("M960 324 V382")
    b += box(
        42,
        389,
        492,
        158,
        "Received-video archive",
        [
            "Private playable segments + provenance",
            "Original aircraft recording stays separate",
        ],
        "PRESERVE CONTEXT",
    )
    b += box(
        612,
        389,
        546,
        158,
        "Saved frame + detector results",
        [
            "Select an original frame; import matched results",
            "Select the intended animal for assessment",
        ],
        "CONNECTED HANDOFF",
    )
    b += arrow("M886 547 V580")
    b += box(
        612,
        587,
        546,
        144,
        "Gemini assessment + triage rules",
        ["Selected still / animal crop only", "Advisory findings; no whole-video model input"],
        None,
    )
    b += arrow("M286 547 V781 H600 V809") + arrow("M886 731 V781 H600 V809")
    b += '<rect x="255" y="815" width="690" height="91" rx="18" fill="#E6F5EF" stroke="#087F8C"/>'
    b += text(280, 853, "Coordinator reviews the same case", 25, INK, 650)
    b += text(
        280,
        884,
        "Original footage + saved photo + advisory finding + human outcome",
        18,
        MUTED,
    )
    b += text(
        42,
        950,
        "PENDING: trained/live YOLO execution, automatic frame shortlisting, patrol alerts and physical-link validation.",
        18,
        GOLD,
    )
    save(
        "judges-drone-evidence.svg",
        988,
        "Drone video to coordinator-reviewed evidence",
        "The private receiver supports recording and saved-frame evidence. Validated external detector output links to selected-animal assessment and rule-based triage. The coordinator can review the received footage and findings. Hardware validation, live YOLO execution, automatic shortlisting and patrol alert creation remain pending.",
        b,
    )


def buttons():
    for name, label, color in [
        ("workflow", "01  EXPLORE THE WORKFLOW", "#087F8C"),
        ("demo", "02  RUN THE DEMO", "#6554B4"),
        ("evidence", "03  REVIEW THE EVIDENCE", "#263D50"),
    ]:
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="255" height="48" viewBox="0 0 255 48" role="img" aria-label="{label}">
<rect width="255" height="48" rx="8" fill="{color}"/>
<text x="127.5" y="29" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="14" font-weight="700" fill="white">{label}</text></svg>'''
        (OUT / f"button-{name}.svg").write_text(svg + "\n")


if __name__ == "__main__":
    buttons()
    overview()
    architecture()
    drone()
    print("Built three self-contained README SVG diagrams.")
