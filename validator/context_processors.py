from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from .models import SiteConfiguration


def site_config(request):
    """Expose the PHI-warning flag and whether bug reporting is configured.

    One indexed primary-key lookup per request. Fail safe: if the table isn't
    migrated yet, assume the warning should show.
    """
    try:
        show = SiteConfiguration.load().show_phi_warning
    except (OperationalError, ProgrammingError):
        show = True
    return {
        "show_phi_warning": show,
        "report_bug_enabled": bool(settings.GITHUB_ISSUE_TOKEN),
    }
