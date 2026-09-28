# LifeJacket Agent 2: Triage & Coordination Agent

## Project Summary

LifeJacket is an agentic AI system for marine wildlife rescue coordination. **Agent 1: Incident Intake Agent** converts reports and images into structured incident records. **Agent 2: Triage & Coordination Agent** uses those records to support triage, response coordination, alert generation, and daily documentation.

The professor-facing deliverable is:

`agent2.ipynb`

## Agent 2 Workflow

Agent 2 is designed as one operational agent containing modular Gemini prompt stages:

1. **Species Classification Prompt Module** categorizes the animal as pinniped, cetacean, sea turtle, or unknown.
2. **Report Validation Prompt Module** identifies incomplete or conflicting report information.
3. **Duplicate Matching Prompt Module** evaluates whether reports may refer to the same incident.
4. **Severity Triage Prompt Module** assigns urgency from Info to Critical.
5. **Recommended Action Prompt Module** recommends monitoring, notification, or immediate escalation.
6. **Dispatch Selection Prompt Module** selects an appropriate rescue center from the provided directory.
7. **Alert Card And Guardrail Prompt Modules** generate coordinator-facing copy and check for unsafe or unsupported statements.
8. **End-of-Day Documentation Prompt Module** records daily cases and unresolved follow-up needs.
9. **Prompt Improvement Module** evaluates and proposes prompt revisions without deploying them automatically.

## Agentic AI Design

The notebook demonstrates actual Vertex AI Gemini chaining: structured output from one prompt module becomes context for the next. Gemini responses are requested as JSON-schema constrained outputs so the workflow is machine-readable and auditable.

The prototype emphasizes prompt engineering instead of embedding extensive decision policy in Python. Python is used for orchestration, file handling, JSON parsing, validation, exports, and fallback/reference logic.

## Safety And Auditability

This is decision support for trained rescue coordinators, not autonomous field response.

Safety-critical features include:

- required Critical escalation triggers for entanglement, wound with bleeding, respiratory distress with unresponsiveness, and cetacean mobility concern
- guardrail and grounding checks before generated alert-card text can be displayed
- an unsafe-output demo where generated wording is held for coordinator review
- preserved structured records for every case, including incomplete reports
- prompt improvement iterations that require human approval before promotion

Weather integration is intentionally deferred in this first prototype so the notebook focuses on the Agent 2 prompt workflow.

## Data And Outputs

Input:

- `agent1_incident_database.csv`: structured incident data from Agent 1
- `agent2_rescue_center_directory.csv`: rescue center directory extracted from the 2026 West Coast Marine Mammal Stranding Network Directory

Demo outputs:

- `agent2_daily_case_log_demo.csv`
- `agent2_end_of_day_report_demo.json`
- `agent2_prompt_iteration_demo.json`

Supporting files:

- `agent2_prompt_library.json`: prompt templates and structured-output contracts
- `agent2_decision_agent.py`: reference Python implementation
- `agent2_decision_agent.ipynb`: full-code reference notebook

## Running In GCP JupyterLab

Upload these files into the same JupyterLab folder:

- `agent2.ipynb`
- `agent2_prompt_library.json`
- `agent2_rescue_center_directory.csv`
- `agent1_incident_database.csv`
- `requirements-notebook.txt`

In a JupyterLab terminal, install the notebook dependency:

```bash
pip install -r requirements-notebook.txt
```

Open `agent2.ipynb` and run cells from top to bottom. It uses the notebook folder as its project directory, so it does not depend on a local computer path. Offline demo sections run without making a Vertex AI model call.

To run the live Gemini chain through Vertex AI, configure your Google Cloud project and location in the JupyterLab terminal before starting the kernel:

```bash
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="global"
export GOOGLE_GENAI_USE_VERTEXAI="True"
export VERTEX_GEMINI_MODEL="publishers/google/models/gemini-3.5-flash"
```

The notebook uses the Google Gen AI SDK with Vertex AI authentication rather than a Gemini API key. The default model resource is `publishers/google/models/gemini-3.5-flash`, matching the Vertex AI model selected for this prototype. Your GCP notebook environment must have permission to call Vertex AI.

## Scope

This prototype demonstrates an explainable, prompt-engineered coordination workflow for wildlife rescue reports. Final operational decisions and any promoted prompt changes require authorized human review.

## Incident Database (Agent 1 to Agent 2 Handoff)

`agent1_incident_database.csv` is the handoff between Agent 1 and Agent 2. `Chatbox/ChatBox_V8.ipynb` appends one row per completed intake conversation (see its "Save To Incident Database" section), and Agent 2 and `lifejacket_app.py` read it.

The column contract is `agent1_incident_schema.json` (45 columns, version 1). The Agent 1 save step refuses to write if the CSV header does not match it. Add new columns only at the end and bump the version.

**This CSV is temporary storage for the prototype.**

- No locking: two sessions saving at once can corrupt rows.
- Append-only: no updates or deletes; corrections are made by hand.
- Not durable on Cloud Run: the container filesystem resets on each deploy or restart.
- Planned replacement: SQLite for local work, then Firestore or Cloud SQL for the deployed app, keeping the same column names.

**Injury flags:** the V8 assessment prompt outputs the 10 injury and distress flags Agent 2 uses (`llm_injury_present`, `llm_wound_present`, `llm_entanglement_present`, `llm_respiratory_distress_present`, and others), and they are saved directly. `reported_color`, `reported_bleeding` and `cv_top3_*` stay empty because V8 does not collect them.
