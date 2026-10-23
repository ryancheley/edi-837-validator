"""RuleSet schema validation + overlay conversion. No live API calls."""

from __future__ import annotations

from validator.guides import schema

_GOOD = {
    "plan_name": "Acme Health",
    "transaction_types": ["837P"],
    "required_elements": [{"ref": "SBR09", "note": "Claim filing indicator required"}],
    "code_restrictions": [{"ref": "SBR09", "allowed": ["MC"], "note": "Medicaid only"}],
    "notes": ["Submit within 90 days"],
}


def test_valid_ruleset_passes():
    assert schema.validate_ruleset(_GOOD) == []


def test_missing_key_is_reported():
    bad = {k: v for k, v in _GOOD.items() if k != "notes"}
    assert any("notes" in e for e in schema.validate_ruleset(bad))


def test_bad_transaction_type_reported():
    bad = {**_GOOD, "transaction_types": ["837X"]}
    assert any("transaction_types" in e for e in schema.validate_ruleset(bad))


def test_code_restriction_needs_allowed_list():
    bad = {**_GOOD, "code_restrictions": [{"ref": "SBR09", "allowed": [], "note": "x"}]}
    assert any("allowed" in e for e in schema.validate_ruleset(bad))


def test_to_overlay_shapes_for_engine():
    overlay = schema.to_overlay(_GOOD)
    assert overlay == {"required": ["SBR09"], "codes": {"SBR09": ["MC"]}}
