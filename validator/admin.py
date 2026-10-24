import json

from django import forms
from django.contrib import admin
from django.forms.fields import InvalidJSONInput

from .models import CompanionGuide, Plan, RuleSet, SiteConfiguration, ValidationRun


class _PrettyJSONField(forms.JSONField):
    """Render stored JSON indented in the admin textarea (still editable)."""

    def prepare_value(self, value):
        if isinstance(value, InvalidJSONInput):
            return value  # keep the user's raw text so they can fix a syntax error
        return json.dumps(value, indent=2, ensure_ascii=False, cls=self.encoder)


class RuleSetAdminForm(forms.ModelForm):
    class Meta:
        model = RuleSet
        fields = "__all__"
        field_classes = {"data": _PrettyJSONField}
        widgets = {"data": forms.Textarea(attrs={"rows": 24, "cols": 100, "style": "font-family: monospace"})}


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = ("__str__", "show_phi_warning")

    def has_add_permission(self, request):
        # Singleton: allow creating the row only if it doesn't exist yet.
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "payer_id", "created_at")
    search_fields = ("name", "payer_id")


@admin.register(CompanionGuide)
class CompanionGuideAdmin(admin.ModelAdmin):
    list_display = ("plan", "status", "uploaded_at")
    list_filter = ("status",)


@admin.register(RuleSet)
class RuleSetAdmin(admin.ModelAdmin):
    form = RuleSetAdminForm
    list_display = ("guide", "is_active", "reviewed_by", "reviewed_at")
    list_filter = ("is_active",)


@admin.register(ValidationRun)
class ValidationRunAdmin(admin.ModelAdmin):
    list_display = ("filename", "txn_type", "plan", "error_count", "created_at")
    list_filter = ("txn_type", "plan")
