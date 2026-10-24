"""View-level tests with the real test client + real engine (no mocks)."""

from __future__ import annotations

import io
import json

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone

from validator.models import CompanionGuide, Plan, RuleSet, ValidationRun
from validator.x12.tests.test_engine import _edi, _i_body, _p_body


@pytest.fixture
def user(db):
    return User.objects.create_user("tester", password="pw12345!")


@pytest.fixture
def client_in(client, user):
    client.force_login(user)
    return client


def _upload(body):
    return io.BytesIO(_edi(body).encode()), "claim.837"


@override_settings(MAX_837_BYTES=16)
def test_oversized_claim_rejected_with_configured_limit(client_in):
    fh = io.BytesIO(b"X" * 64)
    fh.name = "big.837"
    resp = client_in.post("/", {"edi_file": fh})
    assert resp.status_code == 200
    assert b"File too large" in resp.content
    assert ValidationRun.objects.count() == 0  # rejected before validation


def test_validate_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302 and "/login" in resp["Location"]


def test_validate_clean_837p(client_in):
    fh, name = _upload(_p_body())
    fh.name = name
    resp = client_in.post("/", {"edi_file": fh})
    assert resp.status_code == 200
    assert b"Valid" in resp.content
    run = ValidationRun.objects.get()
    assert run.txn_type == "837P"
    assert run.error_count == 0


def test_validate_reports_errors(client_in):
    body = _p_body()
    body[body.index("BHT*0019*00*REF123*20210101*1253*CH")] = "BHT*0019*00*REF123*20210101*1253*XX"
    fh = io.BytesIO(_edi(body).encode())
    fh.name = "bad.837"
    resp = client_in.post("/", {"edi_file": fh})
    assert resp.status_code == 200
    assert b"ELEM.CODE" in resp.content
    assert ValidationRun.objects.get().error_count > 0


def test_validate_with_active_plan_overlay(client_in):
    plan = Plan.objects.create(name="Acme")
    guide = CompanionGuide.objects.create(plan=plan, pdf="companion_guides/x.pdf", status="active")
    RuleSet.objects.create(
        guide=guide,
        is_active=True,
        data={
            "plan_name": "Acme",
            "transaction_types": ["837P"],
            "required_elements": [],
            "code_restrictions": [{"ref": "SBR09", "allowed": ["MC"], "note": "Medicaid only"}],
            "notes": [],
        },
    )
    fh = io.BytesIO(_edi(_p_body()).encode())  # SBR09 = CI, disallowed by plan
    fh.name = "claim.837"
    resp = client_in.post("/", {"edi_file": fh, "plan": str(plan.pk)})
    assert resp.status_code == 200
    assert b"SBR09" in resp.content


def test_validate_form_is_labelled_and_results_is_a_live_region(client_in):
    html = client_in.get("/").content
    assert b'for="edi_file"' in html and b'id="edi_file"' in html
    assert b'for="plan"' in html and b'id="plan"' in html
    assert b'aria-live="polite"' in html  # #results announces after an htmx swap


def test_findings_convey_severity_as_text_not_color_alone(client_in):
    body = _p_body()
    body[body.index("BHT*0019*00*REF123*20210101*1253*CH")] = "BHT*0019*00*REF123*20210101*1253*XX"
    fh = io.BytesIO(_edi(body).encode())
    fh.name = "bad.837"
    resp = client_in.post("/", {"edi_file": fh})
    assert b"Error" in resp.content  # per-finding severity word (capfirst), not colour alone


def test_guide_chip_is_wrapped_in_a_live_region(client_in):
    plan = Plan.objects.create(name="Acme")
    CompanionGuide.objects.create(plan=plan, pdf="companion_guides/x.pdf", status="failed", error="boom")
    assert b'aria-live="polite"' in client_in.get(f"/plans/{plan.pk}/").content


def test_results_show_offending_segment_text_without_persisting_it(client_in):
    body = _p_body()
    body[body.index("BHT*0019*00*REF123*20210101*1253*CH")] = "BHT*0019*00*REF123*20210101*1253*XX"
    fh = io.BytesIO(_edi(body).encode())
    fh.name = "bad.837"
    resp = client_in.post("/", {"edi_file": fh})

    assert resp.status_code == 200
    # The offending BHT segment is rendered in the results for the user to locate.
    assert b"BHT*0019*00*REF123*20210101*1253*XX" in resp.content
    # PHI: the raw segment/content is NOT written to the audit record.
    run = ValidationRun.objects.get()
    assert "REF123" not in json.dumps(run.summary)


def test_export_findings_json_and_csv(client_in):
    body = _p_body()
    body[body.index("BHT*0019*00*REF123*20210101*1253*CH")] = "BHT*0019*00*REF123*20210101*1253*XX"
    fh = io.BytesIO(_edi(body).encode())
    fh.name = "bad.837"
    client_in.post("/", {"edi_file": fh})  # stashes findings in the session

    j = client_in.get("/export/json/")
    assert j.status_code == 200
    assert j["Content-Type"] == "application/json"
    assert "attachment" in j["Content-Disposition"] and "bad-findings.json" in j["Content-Disposition"]
    assert any(f["rule_id"] == "ELEM.CODE" for f in j.json()["findings"])

    c = client_in.get("/export/csv/")
    assert c.status_code == 200
    assert c["Content-Type"] == "text/csv"
    text = c.content.decode()
    assert text.splitlines()[0] == "rule_id,severity,loop,segment_id,segment_pos,element_ref,message"
    assert "ELEM.CODE" in text


def test_export_without_validation_is_404(client_in):
    assert client_in.get("/export/json/").status_code == 404
    assert client_in.get("/export/bogus/").status_code == 404


def test_history_lists_own_runs_and_detail(client_in, user):
    body = _p_body()
    body[body.index("BHT*0019*00*REF123*20210101*1253*CH")] = "BHT*0019*00*REF123*20210101*1253*XX"
    fh = io.BytesIO(_edi(body).encode())
    fh.name = "bad.837"
    client_in.post("/", {"edi_file": fh})

    listing = client_in.get("/history/")
    assert listing.status_code == 200
    assert b"bad.837" in listing.content

    run = ValidationRun.objects.get(user=user)
    detail = client_in.get(f"/history/{run.pk}/")
    assert detail.status_code == 200
    assert b"ELEM.CODE" in detail.content


def test_history_detail_hidden_from_other_users(client, django_user_model):
    owner = django_user_model.objects.create_user("owner", password="pw12345!")
    run = ValidationRun.objects.create(user=owner, filename="owned.837", summary={"findings": []})
    other = django_user_model.objects.create_user("other", password="pw12345!")
    client.force_login(other)
    assert client.get(f"/history/{run.pk}/").status_code == 404
    assert b"owned.837" not in client.get("/history/").content


def test_retry_failed_guide_restarts_extraction(client_in, monkeypatch):
    started: list[int] = []
    monkeypatch.setattr("validator.views._start_extraction", lambda g: started.append(g.pk))
    plan = Plan.objects.create(name="Acme")
    guide = CompanionGuide.objects.create(plan=plan, pdf="companion_guides/x.pdf", status="failed", error="boom")

    resp = client_in.post(f"/guides/{guide.pk}/retry/")
    assert resp.status_code == 200
    guide.refresh_from_db()
    assert guide.status == "pending"
    assert guide.error == ""
    assert started == [guide.pk]  # re-ran against the stored PDF, no re-upload


def test_retry_is_noop_on_non_failed_guide(client_in, monkeypatch):
    started: list[int] = []
    monkeypatch.setattr("validator.views._start_extraction", lambda g: started.append(g.pk))
    plan = Plan.objects.create(name="Acme")
    guide = CompanionGuide.objects.create(plan=plan, pdf="companion_guides/x.pdf", status="active")

    assert client_in.post(f"/guides/{guide.pk}/retry/").status_code == 200
    guide.refresh_from_db()
    assert guide.status == "active" and started == []


def _ruleset(plan, txn_types, restrict_ref, allowed, when):
    guide = CompanionGuide.objects.create(plan=plan, pdf="companion_guides/x.pdf", status="active")
    return RuleSet.objects.create(
        guide=guide,
        is_active=True,
        reviewed_at=when,
        data={
            "plan_name": plan.name,
            "transaction_types": txn_types,
            "required_elements": [],
            "code_restrictions": [{"ref": restrict_ref, "allowed": allowed, "note": "x"}],
            "notes": [],
        },
    )


def test_overlay_selected_by_transaction_type_with_multiple_guides(client_in):
    plan = Plan.objects.create(name="Acme")
    now = timezone.now()
    # 837P guide restricts SBR09; 837I guide restricts BHT06 and is reviewed LATER
    # (so the old most-recent-wins logic would wrongly apply it to 837P too).
    _ruleset(plan, ["837P"], "SBR09", ["MC"], now)
    _ruleset(plan, ["837I"], "BHT06", ["RP"], now + timezone.timedelta(hours=1))

    p = io.BytesIO(_edi(_p_body()).encode())  # SBR09=CI, BHT06=CH
    p.name = "claim.837"
    rp = client_in.post("/", {"edi_file": p, "plan": str(plan.pk)})
    assert b"SBR09" in rp.content  # 837P ruleset applied
    assert b"BHT06" not in rp.content  # 837I ruleset NOT applied despite being newer

    i = io.BytesIO(_edi(_i_body()).encode())  # BHT06=CH
    i.name = "claim.837"
    ri = client_in.post("/", {"edi_file": i, "plan": str(plan.pk)})
    assert b"BHT06" in ri.content  # 837I ruleset applied
    assert b"SBR09" not in ri.content


def test_help_page_renders_with_docs(client_in):
    resp = client_in.get("/help/")
    assert resp.status_code == 200
    assert b"Help &amp; documentation" in resp.content
    assert b"Finding codes" in resp.content and b"ELEM.CODE" in resp.content


def test_help_requires_login(client):
    resp = client.get("/help/")
    assert resp.status_code == 302 and "/login" in resp["Location"]


def test_plan_create_flow(client_in):
    resp = client_in.post("/plans/new/", {"name": "BlueCo", "payer_id": "12345", "notes": ""})
    assert resp.status_code == 302
    assert Plan.objects.filter(name="BlueCo").exists()
