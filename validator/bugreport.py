"""Report-a-bug → GitHub issue.

A logged-in user files a bug from the site; it becomes an issue in the
configured repo. Repo and token come from settings (env), never hardcoded.

Telemetry is **diagnostic only** — app/runtime versions, the page the user came
from, their browser, username, and time. It is built from request metadata and
never touches uploaded claim files, filenames, or validation findings, so it
contains **no PHI** by construction. A secret-redaction pass runs before the
text is sent to the (public) issue as defence in depth.
"""

from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import urllib.error
import urllib.request

import django
from django.conf import settings
from django.utils import timezone

GITHUB_API = "https://api.github.com"

# Long unbroken token-like runs (API keys, PATs, bearer values) — a 20+ char
# run of url-safe characters effectively never occurs in prose, so this strips
# leaked secrets while leaving ordinary diagnostic text intact.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{20,}")


class IssueError(Exception):
    """Raised when an issue could not be filed. Never carries the token."""


def redact(text: str) -> str:
    return _TOKEN_RE.sub("[REDACTED]", text)


def _app_version() -> str:
    try:
        return importlib.metadata.version("edi-validator")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def telemetry(request) -> dict[str, str]:
    """Diagnostic, PHI-free context for a bug report. Only environment/runtime
    facts — nothing derived from an uploaded claim."""
    return {
        "app": f"edi-validator {_app_version()}",
        "python": platform.python_version(),
        "django": django.get_version(),
        "page": request.META.get("HTTP_REFERER", ""),
        "user agent": request.META.get("HTTP_USER_AGENT", ""),
        "user": request.user.get_username(),
        "time": timezone.now().isoformat(timespec="seconds"),
    }


def telemetry_text(request) -> str:
    return "\n".join(f"{k}: {v}" for k, v in telemetry(request).items())


def create_issue(title: str, body: str, labels: list[str] | None = None) -> str:
    """Create a GitHub issue and return its html_url. Raises IssueError on a
    missing token or any API/transport failure (token never included)."""
    token = settings.GITHUB_ISSUE_TOKEN
    if not token:
        raise IssueError("Bug reporting is not configured.")
    payload: dict[str, object] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    request = urllib.request.Request(
        f"{GITHUB_API}/repos/{settings.GITHUB_ISSUE_REPO}/issues",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "edi-validator-bug-reporter",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response).get("html_url", "")
    except urllib.error.HTTPError as exc:
        raise IssueError(f"GitHub rejected the report (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise IssueError(f"Could not reach GitHub: {exc.reason}.") from exc
