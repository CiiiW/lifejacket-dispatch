# Rescue Workflow Ownership

Organize development and demos around these workflows. Existing folders stay
in place; this map defines behavioral ownership, not individual teammates.

## 1. Public Intake

- Entry: `api/routes/intake.py` and `clients/reporter_app/`.
- Orchestration: `services/pipeline.py`; question/stop state: `chatbot/session.py`.
- Model stages: identification, assessment, report generation, report checking
  under `agents/`; shared model transport under `llm/`.
- Deterministic logic: taxonomy, severity, duplicate matching, responder ranking.
- Mass-stranding grouping: `dispatch/mass_stranding.py`, surfaced by incident
  list/detail routes from current case records; not an extra model or agent.
- Writes: repository snapshots, messages, photos, and explicit incident events.
- Boundary: candidate ranking is not a dispatch approval or permit check.

## 2. Coordinator Review

- Entry: incident detail in `clients/responder_console/`; HTTP adapters in
  `api/routes/coordination.py`, `incidents.py`, and `responders.py`.
- Read-only tools: `services/coordination.py` retrieves history, offers,
  derived pending checks, and on-duty responders with recorded workload.
- Actual tool-selection agent: `agents/coordination.py` chooses registered
  tools in a bounded loop. Tool arguments remain application-controlled.
- Outputs: record-backed attention items and fixed next-step proposals.
- Human actions: assignment offers, acceptance/decline, field status, outcomes.
- Boundary: agent checks cannot write, notify, approve, or dispatch. Existing
  mutation endpoints are not a complete authorization or eligibility gate.

## 3. Shift Handover

- Entry: Handover tab and `GET /coordination/handover`.
- Event writer: `services/events.py`, called by repository and mutation routes
  inside their existing transactions.
- Read model: `services/handover.py`; schema: `models/handover.py`.
- Output: UTC-window events plus current open, nonduplicate cases and checks.
- Boundary: deterministic retrieval, no model call or agent. No backfill,
  authenticated actor identity, shift ownership, or center-specific access.

## Data Contracts

| Record/view | Meaning | Not a claim of |
|---|---|---|
| Incident snapshot | Current recorded case state | Every historical transition |
| Assignment | Offered responder and latest response | Verified eligibility or permission |
| Incident event | Explicit application change recorded transactionally | Tamper-proof audit or authenticated actor |
| Pending check | Derived attention item at retrieval time | Persisted task, owner, deadline, acknowledgment |
| Responder availability | Active and on-duty flags plus active assignment IDs | Spare capacity or case suitability |
| Handover | Windowed events and current carryover | Case state at shift end or a generated narrative |

Keep these contracts in `models/`, business behavior in `services/` or the
existing domain modules, and shared HTTP types in `clients/shared/api.ts`.
Clients display backend decisions; they should not duplicate triage rules.

## Team Checkpoints

1. Run the [connected workflow](../demo/connected_workflow.md) before demos.
2. Review API/schema changes together with shared client types and tests.
3. Label scripted and live demonstrations separately.
4. Add authorization, center scope, and operator validation before real use.

See [coordination details](coordination_tools.md) for limits and live evidence.
