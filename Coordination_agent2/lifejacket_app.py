"""Streamlit interface for the prompt-first LifeJacket Agent 2 demonstration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from lifejacket_vertex import DEFAULT_MODEL, VertexPromptChain, clean_record, to_json


APP_DIR = Path(__file__).parent
DEFAULT_INPUT = APP_DIR / "agent1_incident_database.csv"
DEFAULT_RESCUE_CENTERS = APP_DIR / "agent2_rescue_center_directory.csv"
PROMPT_LIBRARY = APP_DIR / "agent2_prompt_library.json"
FEATURED_DEMO_CASE_ID = "INC_80ca122f"
LEVEL_LABELS = {0: "Info", 1: "Monitor", 2: "Respond", 3: "Critical"}


def setup_page() -> None:
    st.set_page_config(
        page_title="LifeJacket | Agent 2",
        page_icon="LJ",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(
        """
        <style>
        :root { --navy:#163249; --ink:#182733; --sea:#087e8b; --critical:#bf3a38;
                --respond:#e2882f; --monitor:#14796b; --line:#dce4e8; --bg:#f5f7f8; }
        .stApp { background: var(--bg); color: var(--ink); }
        h1, h2, h3 { letter-spacing: 0 !important; color: var(--navy); }
        [data-testid="stSidebar"] { background: #edf2f4; border-right: 1px solid var(--line); }
        .summary-grid {
            display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px; margin: 14px 0 18px;
        }
        .summary-tile {
            background: white; border: 1px solid var(--line); border-radius: 6px;
            padding: 10px 12px;
        }
        .summary-name { font-size: 13px; color: #50616d; }
        .summary-number { font-size: 30px; line-height: 1.2; color: var(--ink); }
        .case-strip {
            background: white; border: 1px solid var(--line); border-left: 5px solid var(--sea);
            padding: 12px 14px; border-radius: 6px; margin-bottom: 12px;
        }
        .case-strip.critical { border-left-color: var(--critical); }
        .case-strip.respond { border-left-color: var(--respond); }
        .case-strip.monitor { border-left-color: var(--monitor); }
        .case-label { font-size: 12px; color: #5a6b76; text-transform: uppercase; }
        .case-value { font-size: 16px; font-weight: 650; color: var(--ink); }
        .safety {
            background: #eef6f5; border: 1px solid #b9d8d3; border-radius: 6px;
            padding: 12px; color: #153f3c;
        }
        .pending {
            background: #fff; border: 1px dashed #b7c4ca; border-radius: 6px;
            padding: 14px; color: #50616d;
        }
        div.stButton > button { border-radius: 6px; min-height: 40px; }
        @media (max-width: 640px) {
            .summary-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
            .summary-number { font-size: 25px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def load_default_reports() -> pd.DataFrame:
    return pd.read_csv(DEFAULT_INPUT)


@st.cache_data(show_spinner=False)
def load_rescue_centers() -> pd.DataFrame:
    return pd.read_csv(DEFAULT_RESCUE_CENTERS).fillna("")


@st.cache_data(show_spinner=False)
def load_prompt_catalog() -> pd.DataFrame:
    library = json.loads(PROMPT_LIBRARY.read_text(encoding="utf-8"))
    return pd.DataFrame(library["prompts"])


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def json_bytes(value: Any) -> bytes:
    return (to_json(value) + "\n").encode("utf-8")


def severity_class(level: int) -> str:
    return {1: "monitor", 2: "respond", 3: "critical"}.get(level, "")


def select_case_id(reports: pd.DataFrame) -> str:
    choices = reports["incident_id"].astype(str).tolist()
    default_index = choices.index(FEATURED_DEMO_CASE_ID) if FEATURED_DEMO_CASE_ID in choices else 0
    labels = {
        str(row["incident_id"]): (
            f"{row['incident_id']}  |  {row.get('place_name', '')}"
            + ("  |  Featured demo case" if str(row["incident_id"]) == FEATURED_DEMO_CASE_ID else "")
        )
        for _, row in reports.iterrows()
    }
    return st.selectbox(
        "Selected Agent 1 report",
        choices,
        index=default_index,
        format_func=lambda case_id: labels[case_id],
    )


def render_source_report(record: pd.Series) -> None:
    st.markdown(
        f'<div class="case-strip"><div class="case-label">Agent 1 structured report | awaiting Agent 2 analysis</div>'
        f'<div class="case-value">{record["incident_id"]} | {record.get("place_name", "")}</div>'
        f'<div>Submitted: {record.get("report_timestamp", "")} | '
        f'Likely species: {record.get("llm_likely_species", "Not recorded")}</div></div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        st.write(f"**Reported visible wound:** {record.get('reported_visible_wound', 'Not recorded')}")
        st.write(f"**Reported bleeding:** {record.get('reported_bleeding', 'Not recorded')}")
        st.write(f"**Reported entanglement:** {record.get('reported_entanglement', 'Not recorded')}")
    with right:
        st.write(f"**Reported mobility:** {record.get('reported_mobility', 'Not recorded')}")
        st.write(f"**Reported breathing:** {record.get('reported_breathing_status', 'Not recorded')}")
        st.write(f"**Location source:** {record.get('location_source', 'Not recorded')}")


def render_generated_alert(result: dict[str, Any]) -> None:
    record = result["decision_record"]
    card = result["alert_card_output"]
    level = int(record["severity_level"])
    st.markdown(
        f'<div class="case-strip {severity_class(level)}">'
        f'<div class="case-label">Level {level} | {LEVEL_LABELS[level]} | Gemini-generated alert</div>'
        f'<div class="case-value">{card["alert_card_title_generated"]}</div>'
        f'<div>{card["alert_card_summary_generated"]}</div></div>',
        unsafe_allow_html=True,
    )
    risks = "; ".join(card["alert_card_key_risks_generated"]) or "No identified risks"
    missing = "; ".join(card["alert_card_missing_info_generated"]) or "None"
    next_steps = "; ".join(card["alert_card_next_steps_generated"]) or "Coordinator review"
    st.markdown(f"**Key risks:** {risks}  \n**Missing information:** {missing}")
    st.markdown(
        f'<div class="safety"><strong>Next steps:</strong> {next_steps}</div>',
        unsafe_allow_html=True,
    )


def vertex_settings() -> tuple[str, str, str]:
    with st.sidebar:
        st.subheader("Vertex AI")
        project = st.text_input("Google Cloud project", value=os.getenv("GOOGLE_CLOUD_PROJECT", ""))
        location = st.text_input("Location", value=os.getenv("GOOGLE_CLOUD_LOCATION", "global"))
        model = st.text_input("Model resource", value=os.getenv("VERTEX_GEMINI_MODEL", DEFAULT_MODEL))
        st.caption("Uses the GCP runtime identity. No API key is required.")
    return project, location, model


def completed_decision_rows(results: dict[str, dict[str, Any]]) -> pd.DataFrame:
    records = []
    for incident_id, result in results.items():
        record = result["decision_record"]
        records.append(
            {
                "incident_id": incident_id,
                "species_group": record.get("species_group"),
                "case_quality_status": record.get("case_quality_status"),
                "case_match_status": record.get("case_match_status"),
                "severity_level": record.get("severity_level"),
                "recommended_action": record.get("recommended_action"),
                "dispatch_center_name": record.get("dispatch_center_name"),
                "display_status": result.get("display_status"),
            }
        )
    return pd.DataFrame(records)


def main() -> None:
    setup_page()
    st.title("LifeJacket Agent 2")
    st.caption("Prompt-first Gemini demonstration | Agent 1 report in, constrained triage decision out")

    with st.sidebar:
        st.subheader("Incident Source")
        uploaded = st.file_uploader("Upload Agent 1 CSV", type="csv")
        use_demo = st.checkbox("Use bundled Agent 1 sample", value=uploaded is None)

    project, location, model = vertex_settings()
    centers = load_rescue_centers()
    reports = pd.read_csv(uploaded) if uploaded is not None else load_default_reports()
    if uploaded is None and not use_demo:
        st.info("Upload an Agent 1 CSV or enable the bundled sample to begin.")
        st.stop()

    results: dict[str, dict[str, Any]] = st.session_state.setdefault("agent2_results", {})
    selected_id = select_case_id(reports)
    source_record = reports.loc[reports["incident_id"].astype(str) == selected_id].iloc[0]
    selected_result = results.get(selected_id)
    completed_count = len(results)

    st.markdown(
        '<div class="summary-grid">'
        f'<div class="summary-tile"><div class="summary-name">Agent 1 reports</div><div class="summary-number">{len(reports)}</div></div>'
        f'<div class="summary-tile"><div class="summary-name">Gemini analyses completed</div><div class="summary-number">{completed_count}</div></div>'
        f'<div class="summary-tile"><div class="summary-name">Awaiting analysis</div><div class="summary-number">{max(len(reports) - completed_count, 0)}</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    input_tab, run_tab, decision_tab, daily_tab, prompt_tab = st.tabs(
        ["Agent 1 Input", "Run Agent 2", "Decision Output", "Documentation", "Prompt Modules"]
    )

    with input_tab:
        st.subheader("Incoming Structured Reports")
        st.caption("No triage decision is generated until a report is run through Vertex AI Gemini.")
        for _, item in reports.iterrows():
            item_id = str(item["incident_id"])
            status = "Gemini analysis complete" if item_id in results else "Awaiting Gemini analysis"
            featured = " | Featured demo case" if item_id == FEATURED_DEMO_CASE_ID else ""
            st.markdown(
                f'<div class="case-strip"><div class="case-label">{status}{featured}</div>'
                f'<div class="case-value">{item_id} | {item.get("place_name", "")}</div>'
                f'<div>{item.get("report_timestamp", "")} | Agent 1 likely species: '
                f'{item.get("llm_likely_species", "Not recorded")}</div></div>',
                unsafe_allow_html=True,
            )
        with st.expander("Complete Agent 1 CSV input"):
            st.dataframe(reports, use_container_width=True, hide_index=True)

    with run_tab:
        st.subheader("Run Agent 2 With Vertex AI Gemini")
        st.caption("Selected demonstration report | Generated outputs are JSON-constrained and checked before alert display.")
        render_source_report(source_record)
        can_run = bool(project)
        if not can_run:
            st.warning("Enter your Google Cloud project in the sidebar before running Vertex AI.")
        if st.button("Run selected report through Agent 2", type="primary", disabled=not can_run):
            prior = reports.loc[reports["incident_id"].astype(str) != selected_id]
            try:
                chain = VertexPromptChain(project=project, location=location, model=model)
                with st.status("Running Gemini prompt modules...", expanded=True) as status:
                    result = chain.run_case(
                        source_record,
                        prior_cases=prior,
                        rescue_centers=centers,
                        on_stage=lambda name: st.write(f"Processing: {name}"),
                    )
                    status.update(label="Agent 2 Gemini chain complete", state="complete")
                results[selected_id] = result
                selected_result = result
                st.success("Decision output generated. Open the Decision Output tab to present the result.")
            except Exception as exc:
                st.error(f"Vertex AI call failed: {exc}")
        with st.expander("Agent 1 JSON sent into the chain"):
            st.json(clean_record(source_record.to_dict()))

    with decision_tab:
        st.subheader("Gemini Decision Output")
        if not selected_result:
            st.markdown(
                '<div class="pending">No Agent 2 decision has been generated for this report yet. '
                'Open <strong>Run Agent 2</strong> and execute the Gemini chain.</div>',
                unsafe_allow_html=True,
            )
        else:
            decision = selected_result["decision_record"]
            if selected_result["display_approved"]:
                st.success("Alert card passed guardrail and evidence-grounding checks.")
                render_generated_alert(selected_result)
            else:
                st.error("Generated alert card is held for coordinator review and is not displayed.")
            left, right = st.columns(2)
            with left:
                st.markdown("#### Triage Decision")
                st.write(f"**Species group:** {decision['species_group']}")
                st.write(f"**Report quality:** {decision['case_quality_status']}")
                st.write(f"**Duplicate status:** {decision['case_match_status']}")
                if decision.get("matched_incident_id"):
                    st.write(f"**Matched incident:** {decision['matched_incident_id']}")
                st.write(f"**Severity:** Level {decision['severity_level']} | {LEVEL_LABELS[int(decision['severity_level'])]}")
                st.write(f"**Recommended action:** {decision['recommended_action']}")
            with right:
                st.markdown("#### Dispatch Recommendation")
                st.write(f"**Center:** {decision.get('dispatch_center_name', '') or 'Pending coordinator review'}")
                st.write(f"**Hotline:** {decision.get('dispatch_hotline', '') or 'Not recorded'}")
                st.write(f"**Area:** {decision.get('dispatch_response_area', '') or 'Not recorded'}")
                st.write(f"**Confidence:** {float(decision.get('dispatch_match_confidence', 0)):.0%}")
            with st.expander("Complete Gemini JSON and audit trail"):
                st.json(selected_result)
            st.download_button(
                "Download selected decision JSON",
                data=json_bytes(selected_result),
                file_name=f"agent2_{selected_id}_decision.json",
                mime="application/json",
            )

    with daily_tab:
        st.subheader("Automatic Documentation")
        if not results:
            st.info("Completed Agent 2 cases will be documented here after a Gemini run.")
        else:
            documented = completed_decision_rows(results)
            st.dataframe(documented, use_container_width=True, hide_index=True)
            st.download_button(
                "Download documented case log",
                data=csv_bytes(documented),
                file_name="agent2_documented_case_log.csv",
                mime="text/csv",
            )
            if st.button("Generate Gemini end-of-day briefing", disabled=not bool(project)):
                try:
                    chain = VertexPromptChain(project=project, location=location, model=model)
                    report = chain.document_day(documented.to_dict(orient="records"))
                    st.session_state["daily_report"] = report
                except Exception as exc:
                    st.error(f"Daily documentation call failed: {exc}")
            if "daily_report" in st.session_state:
                report = st.session_state["daily_report"]
                st.json(report)
                st.download_button(
                    "Download daily briefing JSON",
                    data=json_bytes(report),
                    file_name="agent2_end_of_day_report.json",
                    mime="application/json",
                )

    with prompt_tab:
        st.subheader("Prompt Modules And Audit Scope")
        st.caption("These templates define the constrained reasoning stages used when Agent 2 is run.")
        catalog = load_prompt_catalog()
        module_filter = st.selectbox("Inspect module", catalog["id"].tolist())
        chosen = catalog.loc[catalog["id"] == module_filter].iloc[0]
        st.write(f"**Stage:** {chosen['stage']}")
        st.write(f"**Purpose:** {chosen['purpose']}")
        st.code(chosen["template"], language="text")


if __name__ == "__main__":
    main()
