from django.contrib import admin

from .models import CompanionGuide, Plan, RuleSet, ValidationRun


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
    list_display = ("guide", "is_active", "reviewed_by", "reviewed_at")
    list_filter = ("is_active",)


@admin.register(ValidationRun)
class ValidationRunAdmin(admin.ModelAdmin):
    list_display = ("filename", "txn_type", "plan", "error_count", "created_at")
    list_filter = ("txn_type", "plan")
