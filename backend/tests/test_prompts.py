"""Tests that every prompt file is loadable and renders with its agent's values.

A prompt with a typo'd placeholder fails at runtime, inside a live report, on
the one call path that matters. These tests catch it at commit time instead.
"""

from __future__ import annotations

import re

import pytest
from lifejacket.agents.assessment import AssessmentAgent
from lifejacket.agents.guardrail import GuardrailAgent
from lifejacket.agents.identification import IdentificationAgent
from lifejacket.agents.report import ReportAgent
from lifejacket.config import PROMPTS_DIR
from lifejacket.llm.prompts import list_prompts, load_prompt, render_prompt, system_principles
from lifejacket.models.schemas import (
    AnimalGroup,
    AssessmentResult,
    IdentificationResult,
    IncidentReport,
    SpeciesCandidate,
)

#: Agents paired with the keyword arguments their prompt needs. Adding an agent
#: without adding it here means its prompt is never render-tested.
AGENT_CASES = [
    (IdentificationAgent, {}),
    (
        AssessmentAgent,
        {
            "identification": IdentificationResult(
                candidates=[
                    SpeciesCandidate(
                        common_name="Harbor seal",
                        confidence=0.93,
                        animal_group=AnimalGroup.PINNIPED,
                    )
                ]
            )
        },
    ),
    (
        ReportAgent,
        {
            "identification": IdentificationResult(
                candidates=[
                    SpeciesCandidate(
                        common_name="Harbor seal",
                        confidence=0.93,
                        animal_group=AnimalGroup.PINNIPED,
                    )
                ]
            ),
            "assessment": AssessmentResult(),
        },
    ),
    (
        GuardrailAgent,
        {
            "report": IncidentReport(headline="Test", summary="Test summary."),
            "assessment": AssessmentResult(),
        },
    ),
]


def test_prompts_directory_is_not_empty():
    assert list_prompts(), f"No .md prompts found under {PROMPTS_DIR}"


def test_system_principles_loads_and_covers_the_safety_rules():
    """The safety boundary is load-bearing, so assert its content is present.

    These are the specific actions that kill animals. A refactor that drops
    them from the prompt would be silent otherwise.
    """
    text = system_principles().lower()

    for rule in ("never", "touch", "blowhole", "50 yards", "pup", "oiled"):
        assert rule in text, f"System principles no longer mention '{rule}'"


@pytest.mark.parametrize("path", [p.name for p in list_prompts()])
def test_every_prompt_is_readable(path):
    matches = [p for p in list_prompts() if p.name == path]
    relative = matches[0].relative_to(PROMPTS_DIR)
    assert load_prompt(str(relative)).strip()


@pytest.mark.parametrize(
    ("agent_class", "kwargs"), AGENT_CASES, ids=lambda v: getattr(v, "name", "")
)
def test_agent_prompt_renders_with_real_values(agent_class, kwargs):
    """Render each agent's prompt with the values that agent actually supplies.

    `build_prompt_values` and the prompt's placeholders are two halves of one
    contract, and nothing else checks that they agree.
    """
    agent = agent_class.__new__(agent_class)  # avoid constructing an LLM client
    values = agent_class.build_prompt_values(agent, **kwargs)

    rendered = render_prompt(agent_class.prompt_path, **values)

    assert rendered.strip()
    # An unrendered `{placeholder}` means build_prompt_values missed one.
    leftovers = re.findall(r"\{([a-z_]+)\}", rendered)
    assert not leftovers, f"{agent_class.prompt_path} has unrendered placeholders: {leftovers}"


def test_missing_placeholder_names_the_prompt_and_the_field():
    """The default KeyError gives no hint which file is at fault."""
    with pytest.raises(KeyError, match="identification/identify_species.md"):
        render_prompt("identification/identify_species.md", location_summary="only one")


def test_unknown_prompt_lists_what_is_available():
    with pytest.raises(FileNotFoundError, match="Available prompts"):
        load_prompt("identification/does_not_exist.md")
