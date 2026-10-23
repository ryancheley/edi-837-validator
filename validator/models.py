from django.conf import settings
from django.db import models


class SiteConfiguration(models.Model):
    """Singleton site-wide settings, editable in the Django admin."""

    show_phi_warning = models.BooleanField(
        default=True,
        verbose_name='Show "not HIPAA compliant" banner',
        help_text="When on, every page shows a banner warning users not to upload PHI.",
    )

    class Meta:
        verbose_name = "Site configuration"
        verbose_name_plural = "Site configuration"

    def __str__(self) -> str:
        return "Site configuration"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce a single row
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "SiteConfiguration":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Plan(models.Model):
    """A payer/plan whose companion guide adds requirements on top of the TR3."""

    name = models.CharField(max_length=200, unique=True)
    payer_id = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return str(self.name)

    def active_ruleset(self) -> "RuleSet | None":
        return (
            RuleSet.objects.filter(guide__plan=self, is_active=True)
            .order_by("-reviewed_at")
            .first()
        )


class CompanionGuide(models.Model):
    """An uploaded companion-guide PDF and the status of its LLM extraction."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Extracting"
        NEEDS_REVIEW = "needs_review", "Needs review"
        ACTIVE = "active", "Active"
        FAILED = "failed", "Failed"

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="guides")
    pdf = models.FileField(upload_to="companion_guides/")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.plan.name} guide ({self.get_status_display()})"


class RuleSet(models.Model):
    """Structured plan requirements extracted from a companion guide.

    ``data`` matches guides.schema.RULESET_SCHEMA; apply via schema.to_overlay().
    """

    guide = models.ForeignKey(CompanionGuide, on_delete=models.CASCADE, related_name="rulesets")
    data = models.JSONField(default=dict)
    is_active = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"RuleSet for {self.guide.plan.name}" + (" (active)" if self.is_active else "")


class ValidationRun(models.Model):
    """Audit record of a validation. Raw 837 content is never stored (PHI)."""

    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL)
    txn_type = models.CharField(max_length=10, blank=True)
    filename = models.CharField(max_length=255, blank=True)
    error_count = models.IntegerField(default=0)
    summary = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.filename or 'run'} @ {self.created_at:%Y-%m-%d %H:%M} ({self.error_count} errors)"
