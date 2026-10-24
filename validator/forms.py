from django import forms

from .models import Plan

_INPUT = "w-full rounded border border-slate-300 px-3 py-2 focus:border-sky-500 focus:outline-none"


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ["name", "payer_id", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT}),
            "payer_id": forms.TextInput(attrs={"class": _INPUT}),
            "notes": forms.Textarea(attrs={"class": _INPUT, "rows": 3}),
        }


class GuideUploadForm(forms.Form):
    pdf = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"class": _INPUT, "accept": "application/pdf"})
    )


class ReportBugForm(forms.Form):
    title = forms.CharField(max_length=120, widget=forms.TextInput(attrs={"class": _INPUT, "autofocus": True}))
    description = forms.CharField(
        widget=forms.Textarea(attrs={"class": _INPUT, "rows": 4}),
        help_text="What went wrong, and what you were doing. Do not include PHI.",
    )
    diagnostics = forms.CharField(
        required=False,
        label="Diagnostics to attach (editable)",
        widget=forms.Textarea(attrs={"class": _INPUT + " font-mono text-xs", "rows": 8}),
        help_text="Auto-collected diagnostics — review and trim anything you don't want made public.",
    )
