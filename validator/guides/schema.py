"""Plan RuleSet schema + conversion to the engine overlay.

The LLM extracts a companion guide into this shape (structured-output
constrained), a human reviews it, and the engine applies it as an overlay:
- required_elements: Situational elements the plan makes Required (S -> R)
- code_restrictions: elements whose allowed code set the plan narrows
"""

from __future__ import annotations

# JSON Schema passed to the Messages API via output_config.format. Structured
# outputs disallow min/max constraints and require additionalProperties:false.
RULESET_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "plan_name": {"type": "string"},
        "transaction_types": {
            "type": "array",
            "items": {"type": "string", "enum": ["837P", "837I"]},
        },
        "required_elements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ref": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["ref", "note"],
            },
        },
        "code_restrictions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ref": {"type": "string"},
                    "allowed": {"type": "array", "items": {"type": "string"}},
                    "note": {"type": "string"},
                },
                "required": ["ref", "allowed", "note"],
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "plan_name",
        "transaction_types",
        "required_elements",
        "code_restrictions",
        "notes",
    ],
}

_TOP_KEYS = RULESET_SCHEMA["required"]


def validate_ruleset(data: object) -> list[str]:
    """Return a list of human-readable problems; empty list == valid.

    A lightweight structural check (no jsonschema dependency) — a safety net
    behind the API's structured-output guarantee and for human-edited rulesets.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["ruleset must be a JSON object"]
    for key in _TOP_KEYS:
        if key not in data:
            errors.append(f"missing key '{key}'")
    if not isinstance(data.get("plan_name", ""), str):
        errors.append("plan_name must be a string")
    tts = data.get("transaction_types", [])
    if not isinstance(tts, list) or any(t not in ("837P", "837I") for t in tts):
        errors.append("transaction_types must be a list of '837P'/'837I'")
    for item in data.get("required_elements", []) or []:
        if not isinstance(item, dict) or "ref" not in item:
            errors.append(f"required_elements entry missing 'ref': {item!r}")
    for item in data.get("code_restrictions", []) or []:
        if not isinstance(item, dict) or "ref" not in item or "allowed" not in item:
            errors.append(f"code_restrictions entry needs 'ref' and 'allowed': {item!r}")
        elif not isinstance(item["allowed"], list) or not item["allowed"]:
            errors.append(f"code_restrictions '{item.get('ref')}' needs a non-empty allowed list")
    return errors


def to_overlay(data: dict) -> dict:
    """Convert a validated RuleSet into the overlay the engine consumes."""
    return {
        "required": [e["ref"] for e in data.get("required_elements", [])],
        "codes": {
            r["ref"]: list(r["allowed"]) for r in data.get("code_restrictions", [])
        },
    }
