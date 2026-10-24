"""Admin customisations."""

from __future__ import annotations

from validator.admin import RuleSetAdminForm
from validator.models import CompanionGuide, Plan, RuleSet

_DATA = {
    "plan_name": "Acme",
    "transaction_types": ["837P"],
    "required_elements": [],
    "code_restrictions": [],
    "notes": [],
}


def test_ruleset_admin_form_pretty_prints_data(db):
    plan = Plan.objects.create(name="Acme")
    guide = CompanionGuide.objects.create(plan=plan, pdf="companion_guides/x.pdf", status="active")
    ruleset = RuleSet.objects.create(guide=guide, data=_DATA)

    rendered = RuleSetAdminForm(instance=ruleset)["data"].value()
    assert "\n" in rendered  # indented, not a single line
    assert '  "plan_name": "Acme"' in rendered
