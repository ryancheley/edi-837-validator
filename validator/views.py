import csv
import io
import threading

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import GuideUploadForm, PlanForm
from .guides import extract, schema
from .models import CompanionGuide, Plan, RuleSet, ValidationRun
from .x12 import engine, parser
from .x12.errors import Severity, ValidationError


@login_required
def validate_view(request):
    plans = Plan.objects.all().order_by("name")
    if request.method != "POST":
        return render(request, "validator/validate.html", {"plans": plans})

    upload = request.FILES.get("edi_file")
    if upload is None:
        return render(
            request,
            "validator/validate.html",
            {"plans": plans, "error": "Please choose an 837 file to validate."},
        )
    max_bytes = settings.MAX_837_BYTES
    raw = upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return render(
            request,
            "validator/validate.html",
            {"plans": plans, "error": f"File too large (max {max_bytes // (1024 * 1024)} MB)."},
        )

    plan = None
    overlay = None
    plan_id = request.POST.get("plan")
    if plan_id:
        plan = get_object_or_404(Plan, pk=plan_id)
        ruleset = plan.active_ruleset()
        if ruleset:
            overlay = schema.to_overlay(ruleset.data)

    result = engine.validate(raw, overlay=overlay)

    # PHI: persist only structured results and metadata, never the raw 837.
    summary = result.summary()
    ValidationRun.objects.create(
        user=request.user if request.user.is_authenticated else None,
        plan=plan,
        txn_type=result.txn_type or "",
        filename=upload.name,
        error_count=result.error_count,
        summary=summary,
    )
    # Stash the structured findings (no raw claim) so the results page can offer
    # a JSON/CSV download of what the user is currently looking at.
    request.session["last_validation"] = {"filename": upload.name, "summary": summary}

    context = {
        "plans": plans,
        "result": result,
        "grouped": _group_by_loop(result.errors),
        "filename": upload.name,
        "plan": plan,
        # Display-only: lets the results view show the offending segment text.
        # Built from the just-uploaded file, never persisted (PHI stays in memory).
        "segment_text": _segment_text(raw),
    }
    template = "validator/_results.html" if request.headers.get("HX-Request") else "validator/validate.html"
    return render(request, template, context)


def _segment_text(raw: bytes) -> dict[int, str]:
    """Map 1-based segment position -> reconstructed segment text, for display."""
    try:
        doc = parser.parse(raw)
    except parser.ParseError:
        return {}
    sep, term = doc.delimiters.element, doc.delimiters.segment
    return {seg.pos: sep.join(seg.elements) + term for seg in doc.segments}


def _group_by_loop(errors):
    groups: dict[str, list] = {}
    for err in errors:
        groups.setdefault(err.loop or "Envelope / header", []).append(err)
    return groups


_CSV_COLUMNS = ["rule_id", "severity", "loop", "segment_id", "segment_pos", "element_ref", "message"]


@login_required
def export_findings(request, fmt):
    """Download the most recent validation's findings as JSON or CSV.

    Reads the session stash written by ``validate_view`` — structured findings
    only, never raw claim content.
    """
    stash = request.session.get("last_validation")
    if not stash:
        raise Http404("No validation results to export; validate a file first.")
    summary = stash["summary"]
    base = (stash.get("filename") or "validation").rsplit(".", 1)[0]

    if fmt == "json":
        resp = JsonResponse(summary, json_dumps_params={"indent": 2})
        resp["Content-Disposition"] = f'attachment; filename="{base}-findings.json"'
        return resp
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_CSV_COLUMNS)
        for finding in summary.get("findings", []):
            writer.writerow([finding.get(col, "") for col in _CSV_COLUMNS])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{base}-findings.csv"'
        return resp
    raise Http404("Unknown export format")


# --------------------------------------------------------------------------- #
# Plans & companion guides
# --------------------------------------------------------------------------- #
@login_required
def plan_list(request):
    return render(request, "validator/plans.html", {"plans": Plan.objects.all().order_by("name")})


# --------------------------------------------------------------------------- #
# Validation history (ValidationRun audit records — structured findings only)
# --------------------------------------------------------------------------- #
@login_required
def history(request):
    runs = ValidationRun.objects.all() if request.user.is_staff else ValidationRun.objects.filter(user=request.user)
    page = Paginator(runs.select_related("plan"), 25).get_page(request.GET.get("page"))
    return render(request, "validator/history.html", {"page_obj": page})


@login_required
def history_detail(request, pk):
    run = get_object_or_404(ValidationRun, pk=pk)
    if not request.user.is_staff and run.user_id != request.user.id:
        raise Http404("No such validation run")
    findings = [
        ValidationError(
            rule_id=f.get("rule_id", ""),
            message=f.get("message", ""),
            severity=Severity(f.get("severity", "error")),
            loop=f.get("loop"),
            segment_id=f.get("segment_id"),
            segment_pos=f.get("segment_pos"),
            element_ref=f.get("element_ref"),
        )
        for f in run.summary.get("findings", [])
    ]
    return render(
        request,
        "validator/history_detail.html",
        {"run": run, "grouped": _group_by_loop(findings)},
    )


@login_required
def plan_create(request):
    form = PlanForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        plan = form.save()
        return redirect("plan_detail", pk=plan.pk)
    return render(request, "validator/plan_form.html", {"form": form})


@login_required
def plan_detail(request, pk):
    plan = get_object_or_404(Plan, pk=pk)
    return render(
        request,
        "validator/plan_detail.html",
        {"plan": plan, "guides": plan.guides.order_by("-uploaded_at"), "upload_form": GuideUploadForm()},
    )


@login_required
@require_POST
def guide_upload(request, pk):
    plan = get_object_or_404(Plan, pk=pk)
    form = GuideUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "validator/plan_detail.html",
            {"plan": plan, "guides": plan.guides.order_by("-uploaded_at"), "upload_form": form},
        )
    guide = CompanionGuide.objects.create(plan=plan, pdf=form.cleaned_data["pdf"])
    _start_extraction(guide)
    return redirect("plan_detail", pk=plan.pk)


@login_required
def guide_status(request, pk):
    """htmx poll target: returns the status chip + review link for one guide."""
    guide = get_object_or_404(CompanionGuide, pk=pk)
    ruleset = guide.rulesets.order_by("-created_at").first()
    return render(request, "validator/_guide_status.html", {"guide": guide, "ruleset": ruleset})


@login_required
@require_POST
def guide_retry(request, pk):
    """Re-run extraction for a failed guide against its already-stored PDF."""
    guide = get_object_or_404(CompanionGuide, pk=pk)
    if guide.status == CompanionGuide.Status.FAILED:
        guide.status = CompanionGuide.Status.PENDING
        guide.error = ""
        guide.save(update_fields=["status", "error"])
        _start_extraction(guide)
    ruleset = guide.rulesets.order_by("-created_at").first()
    return render(request, "validator/_guide_status.html", {"guide": guide, "ruleset": ruleset})


@login_required
def ruleset_review(request, pk):
    import json

    ruleset = get_object_or_404(RuleSet, pk=pk)
    if request.method == "POST":
        try:
            data = json.loads(request.POST.get("data", ""))
        except json.JSONDecodeError as exc:
            return _render_review(request, ruleset, error=f"Invalid JSON: {exc}")
        errors = schema.validate_ruleset(data)
        if errors:
            return _render_review(request, ruleset, error="; ".join(errors), raw=request.POST.get("data"))
        ruleset.data = data
        ruleset.is_active = request.POST.get("activate") == "on"
        ruleset.reviewed_by = request.user
        ruleset.reviewed_at = timezone.now()
        ruleset.save()
        guide = ruleset.guide
        guide.status = CompanionGuide.Status.ACTIVE if ruleset.is_active else CompanionGuide.Status.NEEDS_REVIEW
        guide.save(update_fields=["status"])
        return redirect("plan_detail", pk=guide.plan.pk)
    return _render_review(request, ruleset)


def _render_review(request, ruleset, error=None, raw=None):
    import json

    return render(
        request,
        "validator/ruleset_review.html",
        {"ruleset": ruleset, "error": error, "raw": raw or json.dumps(ruleset.data, indent=2)},
    )


# --------------------------------------------------------------------------- #
# Background extraction
# ponytail: a thread + status field, not Celery. Swap for a task queue only if
# extraction volume or reliability needs grow.
# --------------------------------------------------------------------------- #
def _start_extraction(guide: CompanionGuide) -> None:
    threading.Thread(target=_run_extraction, args=(guide.pk,), daemon=True).start()


def _run_extraction(guide_pk: int) -> None:
    try:
        guide = CompanionGuide.objects.get(pk=guide_pk)
        guide.status = CompanionGuide.Status.RUNNING
        guide.save(update_fields=["status"])
        with guide.pdf.open("rb") as fh:
            pdf_bytes = fh.read()
        data = extract.extract_ruleset(pdf_bytes, guide.plan.name)
        RuleSet.objects.create(guide=guide, data=data, is_active=False)
        guide.status = CompanionGuide.Status.NEEDS_REVIEW
        guide.error = ""
        guide.save(update_fields=["status", "error"])
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        guide = CompanionGuide.objects.get(pk=guide_pk)
        guide.status = CompanionGuide.Status.FAILED
        guide.error = str(exc)[:2000]
        guide.save(update_fields=["status", "error"])
    finally:
        connection.close()  # thread owns its own DB connection


def healthz(request):
    from django.http import HttpResponse

    return HttpResponse("ok")
