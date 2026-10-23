"""Extract a payer companion guide (PDF) into a structured RuleSet via Claude.

Non-deterministic by nature — the output is a *draft* a human reviews before it
is marked active (see models.CompanionGuide.status).
"""

from __future__ import annotations

import base64
import json

import anthropic
from django.conf import settings

from . import schema

_PROMPT = """\
You are extracting EDI validation requirements from an X12 837 companion guide \
for the payer/plan "{plan_name}".

Companion guides publish plan-specific overrides on top of the base HIPAA TR3 \
implementation guide. Extract ONLY those overrides:

1. required_elements: data elements the plan makes REQUIRED that the TR3 marks \
   as Situational. Use the element reference form (e.g. "SBR09", "NM109", \
   "CLM05-1"). Include a short note quoting or paraphrasing the guide.
2. code_restrictions: elements where the plan restricts the allowed code set to \
   a subset (e.g. only accepts certain claim filing indicator codes). Give the \
   element ref and the exact list of allowed codes.
3. notes: any other plan requirements that do not fit the two buckets above.

Set transaction_types to the 837 variants this guide applies to (837P, 837I, or \
both). Do not invent requirements that are not stated in the document. If the \
guide states no override for a category, return an empty list for it."""


def extract_ruleset(pdf_bytes: bytes, plan_name: str) -> dict:
    """Call Claude with the PDF and return a schema-valid RuleSet dict.

    Raises ValueError if the model output does not satisfy the RuleSet schema,
    or anthropic.APIError on transport/API failures.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not configured")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")

    # ponytail: single-shot PDF document block. Claude accepts PDFs up to 32MB /
    # 600 pages; add pypdf chunking only if real guides exceed that.
    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=16000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _PROMPT.format(plan_name=plan_name)},
                ],
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": schema.RULESET_SCHEMA}},
    )

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model did not return valid JSON: {exc}") from exc

    errors = schema.validate_ruleset(data)
    if errors:
        raise ValueError("Extracted ruleset failed validation: " + "; ".join(errors))
    return data
