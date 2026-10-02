"""Vertex AI Gemini prompt-chain utilities for the LifeJacket Streamlit app."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import pandas as pd


DEFAULT_PROMPT_LIBRARY = Path(__file__).with_name("agent2_prompt_library.json")
DEFAULT_MODEL = "publishers/google/models/gemini-3.5-flash"

STRING = {"type": "string"}
STRING_LIST = {"type": "array", "items": {"type": "string"}}
NUMBER_01 = {"type": "number", "minimum": 0, "maximum": 1}


def object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties)}


SCHEMAS = {
    "species": object_schema(
        {
            "species_group": {
                "type": "string",
                "enum": ["pinniped", "cetacean", "sea_turtle", "unknown"],
            },
            "species_group_confidence": NUMBER_01,
            "evidence_used": STRING_LIST,
            "uncertainty_notes": STRING,
            "needs_human_species_review": {"type": "boolean"},
        }
    ),
    "validation": object_schema(
        {
            "case_quality_status": {
                "type": "string",
                "enum": ["complete", "review_needed", "incomplete"],
            },
            "data_conflict_flag": {"type": "boolean"},
            "needs_more_info": {"type": "boolean"},
            "missing_info": STRING_LIST,
            "validation_rationale": STRING,
        }
    ),
    "duplicate": object_schema(
        {
            "case_match_status": {
                "type": "string",
                "enum": [
                    "new_incident",
                    "possible_duplicate",
                    "probable_duplicate",
                    "not_evaluable",
                ],
            },
            "matched_incident_id": {"type": ["string", "null"]},
            "match_confidence": NUMBER_01,
            "match_rationale": STRING,
            "uncertainty_notes": STRING,
        }
    ),
    "severity": object_schema(
        {
            "severity_level": {"type": "integer", "enum": [0, 1, 2, 3]},
            "severity_score": {"type": "number"},
            "severity_confidence": NUMBER_01,
            "triage_reason_codes": STRING_LIST,
            "triggered_rules": STRING_LIST,
            "triage_rationale": STRING,
        }
    ),
    "action": object_schema(
        {
            "recommended_action": {
                "type": "string",
                "enum": [
                    "Guidance only",
                    "Volunteer monitor",
                    "Notify rescue center",
                    "Immediate escalation",
                ],
            },
            "alert_type": STRING,
            "alert_priority": STRING,
            "volunteer_allowed": {"type": "boolean"},
            "coordinator_review_required": {"type": "boolean"},
            "rationale": STRING,
        }
    ),
    "dispatch": object_schema(
        {
            "dispatch_center_name": STRING,
            "dispatch_hotline": STRING,
            "dispatch_email": STRING,
            "dispatch_website": STRING,
            "dispatch_response_area": STRING,
            "dispatch_response_type": STRING,
            "dispatch_match_confidence": NUMBER_01,
            "dispatch_match_reason": STRING,
            "dispatch_alternate_centers": STRING_LIST,
        }
    ),
    "alert_card": object_schema(
        {
            "alert_card_title_generated": STRING,
            "alert_card_summary_generated": STRING,
            "alert_card_key_risks_generated": STRING_LIST,
            "alert_card_missing_info_generated": STRING_LIST,
            "alert_card_next_steps_generated": STRING_LIST,
        }
    ),
    "guardrail": object_schema(
        {
            "pass_guardrails": {"type": "boolean"},
            "violations": STRING_LIST,
            "missing_required_content": STRING_LIST,
            "invented_or_unsupported_claims": STRING_LIST,
            "corrected_copy_if_needed": STRING,
        }
    ),
    "grounding": object_schema(
        {
            "grounded": {"type": "boolean"},
            "unsupported_claims": STRING_LIST,
            "changed_decisions": STRING_LIST,
            "unsafe_language": STRING_LIST,
            "recommended_action": STRING,
        }
    ),
    "audit": object_schema(
        {
            "audit_summary": STRING,
            "inputs_used": STRING_LIST,
            "rules_triggered": STRING_LIST,
            "outputs_generated": STRING_LIST,
            "residual_risks": STRING_LIST,
        }
    ),
    "documentation": object_schema(
        {
            "report_date": STRING,
            "total_cases_documented": {"type": "integer"},
            "severity_counts": {"type": "object"},
            "critical_incidents": STRING_LIST,
            "dispatches_recorded": {"type": "array", "items": {"type": "object"}},
            "unresolved_or_followup_cases": STRING_LIST,
            "duplicate_incident_notes": STRING_LIST,
            "chronological_case_log": {"type": "array", "items": {"type": "object"}},
            "next_shift_attention_items": STRING_LIST,
            "audit_statement": STRING,
        }
    ),
}


def to_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned = {}
    for key, value in record.items():
        cleaned[key] = None if pd.isna(value) else value
    return cleaned


class VertexPromptChain:
    """Runs LifeJacket prompt modules through Gemini on Vertex AI."""

    def __init__(
        self,
        project: str,
        location: str = "global",
        model: str = DEFAULT_MODEL,
        prompt_library_path: Path = DEFAULT_PROMPT_LIBRARY,
    ) -> None:
        if not project:
            raise ValueError("A Google Cloud project ID is required for Vertex AI.")
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
        from google import genai
        from google.genai.types import HttpOptions

        self.client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=HttpOptions(api_version="v1"),
        )
        self.model = model
        library = json.loads(prompt_library_path.read_text(encoding="utf-8"))
        self.prompts = {prompt["id"]: prompt["template"] for prompt in library["prompts"]}

    def render(self, prompt_id: str, **values: Any) -> str:
        return self.prompts[prompt_id].format(**values)

    def call(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "response_json_schema": schema,
            },
        )
        return json.loads(response.text)

    def run_case(
        self,
        row: pd.Series,
        prior_cases: pd.DataFrame,
        rescue_centers: pd.DataFrame,
        on_stage: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        incident = clean_record(row.to_dict())
        outputs: dict[str, Any] = {}

        def stage(name: str) -> None:
            if on_stage:
                on_stage(name)

        species_input = {
            key: incident.get(key)
            for key in [
                "cv_top1_species",
                "cv_top1_confidence",
                "cv_top2_species",
                "cv_top2_confidence",
                "llm_likely_species",
                "llm_species_confidence",
                "reported_mobility",
                "place_name",
            ]
        }
        stage("Species Classification")
        outputs["species_output"] = self.call(
            self.render("species_group_classifier_few_shot", species_json=to_json(species_input)),
            SCHEMAS["species"],
        )
        record = {**incident, **outputs["species_output"]}

        stage("Report Validation")
        outputs["validation_output"] = self.call(
            self.render("report_validation_prompt", incident_packet_json=to_json(record)),
            SCHEMAS["validation"],
        )
        record.update(outputs["validation_output"])

        stage("Duplicate Matching")
        candidates = [clean_record(item) for item in prior_cases.to_dict(orient="records")]
        outputs["duplicate_output"] = self.call(
            self.render(
                "duplicate_matching_prompt",
                current_incident_json=to_json(record),
                prior_candidates_json=to_json(candidates),
            ),
            SCHEMAS["duplicate"],
        )
        record.update(outputs["duplicate_output"])

        stage("Severity Triage")
        outputs["severity_output"] = self.call(
            self.render("severity_triage_prompt", incident_packet_json=to_json(record)),
            SCHEMAS["severity"],
        )
        record.update(outputs["severity_output"])

        stage("Recommended Action")
        outputs["action_output"] = self.call(
            self.render("recommended_action_prompt", severity_packet_json=to_json(record)),
            SCHEMAS["action"],
        )
        record.update(outputs["action_output"])

        stage("Dispatch Selection")
        directory = [clean_record(item) for item in rescue_centers.to_dict(orient="records")]
        outputs["dispatch_output"] = self.call(
            self.render(
                "dispatch_center_prompt",
                incident_packet_json=to_json(record),
                rescue_center_directory_json=to_json(directory),
            ),
            SCHEMAS["dispatch"],
        )
        record.update(outputs["dispatch_output"])

        stage("Alert Card")
        outputs["alert_card_output"] = self.call(
            self.render(
                "alert_card_generator",
                severity_level=record["severity_level"],
                recommended_action=record["recommended_action"],
                dispatch_center_name=record["dispatch_center_name"],
                dispatch_hotline=record["dispatch_hotline"],
                volunteer_allowed=record["volunteer_allowed"],
                coordinator_review_required=record["coordinator_review_required"],
                agent2_record_json=to_json(record),
            ),
            SCHEMAS["alert_card"],
        )

        stage("Guardrail Checks")
        outputs["guardrail_output"] = self.call(
            self.render(
                "alert_card_guardrail_critic",
                agent2_record_json=to_json(record),
                generated_alert_json=to_json(outputs["alert_card_output"]),
            ),
            SCHEMAS["guardrail"],
        )
        outputs["grounding_output"] = self.call(
            self.render(
                "claim_grounding_auditor",
                incident_packet_json=to_json(record),
                generated_text=to_json(outputs["alert_card_output"]),
            ),
            SCHEMAS["grounding"],
        )

        stage("Audit Narrative")
        outputs["audit_output"] = self.call(
            self.render("audit_log_narrator", agent2_record_json=to_json({**record, **outputs})),
            SCHEMAS["audit"],
        )
        outputs["display_approved"] = bool(
            outputs["guardrail_output"]["pass_guardrails"]
            and outputs["grounding_output"]["grounded"]
        )
        outputs["display_status"] = (
            "approved_for_display" if outputs["display_approved"] else "held_for_coordinator_review"
        )
        outputs["decision_record"] = record
        return outputs

    def document_day(self, case_records: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = self.render(
            "end_of_day_documentation_prompt",
            daily_case_records_json=to_json(case_records),
        )
        return self.call(prompt, SCHEMAS["documentation"])

