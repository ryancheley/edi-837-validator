from django.db.utils import OperationalError, ProgrammingError

from .models import SiteConfiguration


def site_config(request):
    """Expose the PHI-warning flag to every template.

    One indexed primary-key lookup per request. Fail safe: if the table isn't
    migrated yet, assume the warning should show.
    """
    try:
        show = SiteConfiguration.load().show_phi_warning
    except (OperationalError, ProgrammingError):
        show = True
    return {"show_phi_warning": show}
