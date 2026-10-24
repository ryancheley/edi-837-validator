"""Report-a-bug → GitHub issue."""

from __future__ import annotations

import pytest
from django.test import override_settings

from validator import bugreport


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user("tester", password="pw12345!")


@pytest.fixture
def client_in(client, user):
    client.force_login(user)
    return client


def test_redact_strips_token_like_runs():
    assert bugreport.redact("key=ghp_abcdefghij1234567890XYZ end") == "key=[REDACTED] end"
    assert bugreport.redact("short values stay") == "short values stay"


def test_telemetry_is_diagnostic_only_no_phi(rf, user):
    req = rf.get("/report/", HTTP_REFERER="/validate/", HTTP_USER_AGENT="TestUA/1.0")
    req.user = user
    data = bugreport.telemetry(req)
    # A fixed, safe allowlist — nothing derived from an uploaded claim.
    assert set(data) == {"app", "python", "django", "page", "user agent", "user", "time"}
    assert data["user"] == "tester" and data["user agent"] == "TestUA/1.0"


@override_settings(GITHUB_ISSUE_TOKEN="")
def test_report_disabled_without_token(client_in):
    assert client_in.get("/report/").status_code == 404


@override_settings(GITHUB_ISSUE_TOKEN="x")
def test_report_form_prefills_diagnostics(client_in):
    html = client_in.get("/report/").content
    assert b"Report a bug" in html and b"python:" in html


@override_settings(GITHUB_ISSUE_TOKEN="x")
def test_report_creates_issue_with_redacted_diagnostics(client_in, monkeypatch):
    calls = {}

    def fake_create(title, body, labels=None):
        calls.update(title=title, body=body, labels=labels)
        return "https://github.com/ryancheley/edi-837-validator/issues/99"

    monkeypatch.setattr("validator.bugreport.create_issue", fake_create)

    resp = client_in.post(
        "/report/",
        {
            "title": "Upload fails",
            "description": "clicking validate did nothing",
            "diagnostics": "python: 3.15\ntoken=ghp_abcdefghij1234567890XYZ",
        },
    )
    assert resp.status_code == 200
    assert b"issues/99" in resp.content
    assert calls["labels"] == ["bug"]
    assert "clicking validate did nothing" in calls["body"]
    assert "## Diagnostics" in calls["body"]
    assert "[REDACTED]" in calls["body"] and "ghp_abcdefghij" not in calls["body"]


@override_settings(GITHUB_ISSUE_TOKEN="x")
def test_report_failure_preserves_draft(client_in, monkeypatch):
    def boom(title, body, labels=None):
        raise bugreport.IssueError("GitHub rejected the report (HTTP 403).")

    monkeypatch.setattr("validator.bugreport.create_issue", boom)

    resp = client_in.post(
        "/report/",
        {"title": "x", "description": "my description", "diagnostics": ""},
    )
    assert resp.status_code == 200
    assert b"Not filed" in resp.content
    assert b"my description" in resp.content  # draft preserved for retry
