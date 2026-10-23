"""PHI-warning banner driven by the SiteConfiguration singleton."""

from __future__ import annotations

import pytest

from validator.models import SiteConfiguration

_BANNER = b"not HIPAA compliant"


def test_singleton_always_pk_1(db):
    a = SiteConfiguration.load()
    a.show_phi_warning = False
    a.save()
    b = SiteConfiguration.load()
    assert a.pk == 1 and b.pk == 1
    assert b.show_phi_warning is False
    assert SiteConfiguration.objects.count() == 1


def test_banner_shown_by_default(client, db):
    # Default (no row yet) fails safe to showing the warning.
    resp = client.get("/accounts/login/")
    assert _BANNER in resp.content


def test_banner_hidden_when_flag_off(client, db):
    cfg = SiteConfiguration.load()
    cfg.show_phi_warning = False
    cfg.save()
    resp = client.get("/accounts/login/")
    assert _BANNER not in resp.content


@pytest.mark.parametrize("flag", [True, False])
def test_banner_follows_flag(client, db, flag):
    cfg = SiteConfiguration.load()
    cfg.show_phi_warning = flag
    cfg.save()
    resp = client.get("/accounts/login/")
    assert (_BANNER in resp.content) is flag
