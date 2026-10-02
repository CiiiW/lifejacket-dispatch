"""Helpers for building the JSON Schemas that constrain model output.

Gemini's JSON mode takes a schema and guarantees the reply matches it. Writing
those schemas by hand is verbose and easy to get subtly wrong, so each agent
builds its schema from the primitives here.

The convention that matters: **every field is required**. A model allowed to
omit `bleeding` will omit it on exactly the cases where bleeding is ambiguous,
which are the cases we most need an answer for. Forcing `false` over silence
means a missing flag is a real negative rather than an unknown.
"""

from __future__ import annotations

from typing import Any

# --- Primitives ------------------------------------------------------------

STRING: dict[str, Any] = {"type": "string"}
BOOLEAN: dict[str, Any] = {"type": "boolean"}
INTEGER: dict[str, Any] = {"type": "integer"}
NUMBER: dict[str, Any] = {"type": "number"}

#: A probability. Bounded so the model cannot return 1.7 or -0.2.
UNIT_INTERVAL: dict[str, Any] = {"type": "number", "minimum": 0.0, "maximum": 1.0}

STRING_LIST: dict[str, Any] = {"type": "array", "items": STRING}


def enum_of(*values: str) -> dict[str, Any]:
    """A string restricted to a fixed set of values.

    Prefer this over a free-text field with instructions about allowed values.
    The decoder enforces an enum; a prompt only requests one.
    """
    return {"type": "string", "enum": list(values)}


def object_schema(
    properties: dict[str, Any], *, required: list[str] | None = None
) -> dict[str, Any]:
    """Build an object schema, requiring every property unless told otherwise.

    Args:
        properties: Field name to field schema.
        required: Explicit required list. Defaults to all properties.
    """
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
    }


def array_of(item_schema: dict[str, Any], *, max_items: int | None = None) -> dict[str, Any]:
    """An array of objects, optionally capped.

    Capping matters for candidate lists: an uncapped "list the species it could
    be" invites a long tail of 0.01-confidence guesses that add noise.
    """
    schema: dict[str, Any] = {"type": "array", "items": item_schema}
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


# --- Shared fragments ------------------------------------------------------
# Reused across agents so that, for example, a species candidate has the same
# shape whether it came from identification or from a responder's correction.

SPECIES_CANDIDATE = object_schema(
    {
        "common_name": STRING,
        "scientific_name": STRING,
        # Genus and family let probability be pooled up the taxonomy, so two
        # hard-to-separate species can still add up to a confident family.
        "genus": STRING,
        "genus_common_name": STRING,
        "family": STRING,
        "family_common_name": STRING,
        "confidence": UNIT_INTERVAL,
        "animal_group": enum_of(
            "pinniped",
            "cetacean",
            "sea_turtle",
            "seabird",
            "other_marine",
            "terrestrial",
            "domestic_animal",
            "unknown",
        ),
    }
)

CLARIFYING_QUESTION = object_schema(
    {
        "question": STRING,
        "rationale": STRING,
        "options": STRING_LIST,
        "feature": STRING,
    }
)
