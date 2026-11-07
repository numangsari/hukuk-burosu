import datetime as dt

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.imports import portal_status
from apps.imports.models import PortalConnection, PortalLawyerAccess

pytestmark = pytest.mark.django_db

NOW = timezone.now()


def connection(user, uyap="tamamlandi", uets="tamamlandi", seen=None, **extra):
    return PortalConnection.objects.create(
        key_hash=f"anahtar-{user.pk}-{PortalConnection.objects.count()}",
        owner=user,
        last_seen=seen if seen is not None else timezone.now(),
        uyap_status=uyap,
        uets_status=uets,
        **extra,
    )


def lawyer(name="Ayşe", surname="Avukat", role=User.Role.LAWYER):
    return User.objects.create_user(
        username=f"{name}-{surname}".lower(), first_name=name, last_name=surname, role=role
    )


def state(indicator, source):
    return next(row["state"] for row in indicator["sources"] if row["key"] == source)


def test_no_connection_is_grey():
    indicator = portal_status.portal_indicator(lawyer())
    assert state(indicator, "uyap") == "yok" and state(indicator, "uets") == "yok"


def test_recent_scan_with_open_session_is_active():
    user = lawyer()
    connection(user)
    indicator = portal_status.portal_indicator(user)
    assert state(indicator, "uyap") == "aktif" and state(indicator, "uets") == "aktif"


@pytest.mark.parametrize(
    "status", ["oturum_yok", "sekme_yok", "sunucu_yok", "izin_yok", "sekme_hazir_degil", "bekliyor"]
)
def test_closed_session_or_missing_tab_is_passive(status):
    user = lawyer()
    connection(user, uyap=status)
    assert state(portal_status.portal_indicator(user), "uyap") == "pasif"


def test_silent_extension_is_passive_even_if_last_status_was_good():
    user = lawyer()
    connection(user, seen=timezone.now() - dt.timedelta(minutes=10))
    assert state(portal_status.portal_indicator(user), "uyap") == "pasif"


def test_mixed_lawyers_are_partial_and_listed_by_name_for_lawyers():
    viewer = lawyer("Ali", "Yönetici", role=User.Role.ADMIN)
    online = lawyer("Ayşe", "Açık")
    offline = lawyer("Veli", "Kapalı")
    connection(online)
    connection(offline, uyap="oturum_yok")
    indicator = portal_status.portal_indicator(viewer)
    row = next(r for r in indicator["sources"] if r["key"] == "uyap")
    assert row["state"] == "kismi"
    assert {(p["name"], p["state"]) for p in row["people"]} == {
        ("Ayşe Açık", "aktif"),
        ("Veli Kapalı", "pasif"),
    }
    assert indicator["show_names"] is True


def test_non_lawyer_sees_colour_but_no_names():
    secretary = lawyer("Sema", "Sekreter", role=User.Role.SECRETARY)
    connection(lawyer())
    indicator = portal_status.portal_indicator(secretary)
    assert state(indicator, "uyap") == "aktif"
    assert indicator["show_names"] is False
    assert all(not row["people"] for row in indicator["sources"])


def test_inactive_connection_and_inactive_owner_are_ignored():
    owner = lawyer()
    connection(owner, active=False)
    other = lawyer("Pasif", "Kişi")
    connection(other)
    other.is_active = False
    other.save()
    assert state(portal_status.portal_indicator(owner), "uyap") == "yok"


def test_pair_link_offered_only_to_permitted_unconnected_user():
    user = lawyer()
    assert portal_status.portal_indicator(user)["can_pair"] is False
    PortalLawyerAccess.objects.create(user=user, identity_number="10000000146", uyap_enabled=True)
    assert portal_status.portal_indicator(user)["can_pair"] is True
    connection(user)
    assert portal_status.portal_indicator(user)["can_pair"] is False


def test_indicator_view_renders_for_logged_in_user_and_requires_login():
    user = lawyer()
    connection(user)
    client = Client()
    assert client.get(reverse("portal_indicator")).status_code == 302
    client.force_login(user)
    response = client.get(reverse("portal_indicator"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "UYAP" in html and "UETS" in html


def test_topbar_contains_indicator_on_regular_pages():
    user = lawyer()
    client = Client()
    client.force_login(user)
    html = client.get(reverse("cases:list")).content.decode()
    assert 'id="portal-indicator"' in html
