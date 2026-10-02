"""LifeJacket Dispatch: agentic AI for stranded and injured animal rescue.

Package map (see the repository README for the full tour):

    agents/     The three LLM agents: identification, assessment, report,
                plus the guardrail reviewer that checks the report.
    chatbot/    Conversation state machine (when to ask, when to stop) and
                the notebook playground. Separate from `agents/` because
                this is flow control, not model reasoning.
    context/    External data: weather, tides, reverse geocoding.
    dispatch/   Deterministic scoring: severity, duplicates, responder match.
                No LLM calls here, on purpose -- see dispatch/severity.py.
    llm/        The single place we talk to a language model.
    models/     Domain schemas, database tables, and the repository layer.
    services/   Orchestration. `services/pipeline.py` is the end-to-end flow.
    api/        FastAPI routes. Thin: no business logic.

    taxonomy.py Pools species probabilities into genus/family answers.
    geo.py      Distance maths.
    config.py   Every setting.

Full walkthrough: docs/backend_tour.md
"""

__version__ = "2.0.0"
