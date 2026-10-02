"""Loading and rendering prompts from the `prompts/` directory.

Prompts live in Markdown files, not in Python string literals. This is the
single most useful convention in the repo for a research project:

- A prompt change shows up as a readable diff in code review.
- Non-programmers on the team can edit prompts without touching Python.
- Prompts can be versioned and A/B tested by swapping a directory.

Templates use `{placeholder}` syntax rendered by `str.format`. Any literal
braces in a prompt must be doubled (`{{` and `}}`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from lifejacket.config import PROMPTS_DIR


class PromptNotFoundError(FileNotFoundError):
    """Raised when a prompt file does not exist, listing what is available."""


@lru_cache
def load_prompt(relative_path: str) -> str:
    """Read a prompt file, e.g. `load_prompt("identification/species_id.md")`.

    Cached: prompts are read on every incident and only change between runs.
    Restart the server after editing one.
    """
    path = PROMPTS_DIR / relative_path
    if not path.exists():
        available = sorted(
            str(p.relative_to(PROMPTS_DIR)) for p in PROMPTS_DIR.rglob("*.md")
        )
        raise PromptNotFoundError(
            f"No prompt at {relative_path}. Available prompts:\n  "
            + "\n  ".join(available)
        )
    return path.read_text(encoding="utf-8").strip()


def render_prompt(relative_path: str, **values: object) -> str:
    """Load a prompt and substitute `{placeholder}` values.

    Raises a clear error naming the missing placeholder, because the default
    `KeyError: 'tide_summary'` gives no hint about which file is at fault.
    """
    template = load_prompt(relative_path)
    try:
        return template.format(**values)
    except KeyError as exc:
        raise KeyError(
            f"Prompt {relative_path} needs placeholder {exc} but it was not provided. "
            f"Provided: {sorted(values)}"
        ) from exc


@lru_cache
def system_principles() -> str:
    """The standing safety and scope rules sent with every agent call.

    Kept separate from task prompts because these must never be overridden by
    a task-specific instruction -- they are what stops the system telling a
    member of the public to approach an injured sea lion.
    """
    return load_prompt("system_principles.md")


def clear_prompt_cache() -> None:
    """Forget cached prompts so edits to `prompts/*.md` take effect.

    Call this in a notebook after editing a prompt file. The API server picks
    up edits on restart instead.
    """
    load_prompt.cache_clear()
    system_principles.cache_clear()


def list_prompts() -> list[Path]:
    """Every prompt file in the repo. Used by tests to check they all render."""
    return sorted(PROMPTS_DIR.rglob("*.md"))
