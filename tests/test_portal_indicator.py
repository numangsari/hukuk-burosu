import datetime as dt

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.imports import portal_status
from apps.imports.models import PortalConnection, PortalLawyerAccess

pytestmark = pytest.mark.django_db


def person(name="Ayşe", surname="Avukat", role=User.Role.LAWYER, **access):
    user = User.objects.create_user(
        username=f"{name}-{surname}".lower(), first_name=name, last_name=surname, role=role
    )
    values = {"uyap_enabled": True, "uets_enabled": True, **access}
    record = PortalLawyerAccess.objects.create(
        user=user, identity_number=f"1000000{User.objects.count():04d}", **values
    )
    return user, record


def admin():
    return User.objects.create_user(username="yonetici", role=User.Role.ADMIN)


def connect(owner, uyap=None, uets=None, status="tamamlandi", seen=None, **extra):
    """Ana bilgisayardaki eklenti bağlantısı; `uyap`/`uets` o an açık olan avukat izni."""
    return PortalConnection.objects.create(
        key_hash=f"anahtar-{PortalConnection.objects.count()}",
        owner=owner,
        last_seen=seen if seen is not None else timezone.now(),
        uyap_status=status,
        uets_status=status,
        uyap_account=uyap,
        uets_account=uets,
        uyap_session_ok=True if uyap else None,
        uyap_session_at=timezone.now() if uyap else None,
        uets_session_ok=True if uets else None,
        uets_session_at=timezone.now() if uets else None,
        **extra,
    )


def row(indicator, source):
    return next(item for item in indicator["sources"] if item["key"] == source)


def people(indicator, source):
    return {p["name"]: p["state"] for p in row(indicator, source)["people"]}


def test_no_permitted_lawyer_is_grey():
    indicator = portal_status.portal_indicator(admin())
    assert row(indicator, "uyap")["state"] == "yok"
    assert row(indicator, "uets")["state"] == "yok"
    assert row(indicator, "uyap")["people"] == []


def test_permitted_lawyer_without_extension_is_passive():
    person()
    indicator = portal_status.portal_indicator(admin())
    assert row(indicator, "uyap")["state"] == "pasif"
    assert people(indicator, "uyap") == {"Ayşe Avukat": "pasif"}


def test_open_session_for_that_lawyer_is_active_per_source():
    owner = admin()
    _, access = person()
    connect(owner, uyap=access)
    indicator = portal_status.portal_indicator(owner)
    assert people(indicator, "uyap") == {"Ayşe Avukat": "aktif"}
    assert row(indicator, "uyap")["state"] == "aktif"
    # UETS'te bu avukatın hesabı açık değil.
    assert row(indicator, "uets")["state"] == "pasif"


def test_account_open_in_browser_is_attributed_to_that_lawyer_only():
    owner = admin()
    _, ayse = person("Ayşe", "Avukat")
    _, veli = person("Veli", "Avukat")
    connect(owner, uyap=ayse, uets=ayse)
    indicator = portal_status.portal_indicator(owner)
    assert people(indicator, "uyap") == {"Ayşe Avukat": "aktif", "Veli Avukat": "pasif"}
    assert row(indicator, "uyap")["state"] == "kismi"
    assert veli.pk != ayse.pk


def test_silent_extension_makes_everything_passive():
    owner = admin()
    _, access = person()
    connect(owner, uyap=access, seen=timezone.now() - dt.timedelta(minutes=10))
    assert row(portal_status.portal_indicator(owner), "uyap")["state"] == "pasif"


def test_closed_session_is_passive_even_with_matching_account():
    owner = admin()
    _, access = person()
    connection = connect(owner, uyap=access)
    connection.uyap_session_ok = False
    connection.save()
    assert row(portal_status.portal_indicator(owner), "uyap")["state"] == "pasif"


def test_only_enabled_active_lawyers_are_listed():
    owner = admin()
    person("Ayşe", "Açık")
    person("Veli", "KapalıUyap", uyap_enabled=False)
    person("Sema", "Stajyer", role=User.Role.INTERN)
    inactive, _ = person("Pasif", "Kişi")
    inactive.is_active = False
    inactive.save()
    indicator = portal_status.portal_indicator(owner)
    assert set(people(indicator, "uyap")) == {"Ayşe Açık"}
    assert set(people(indicator, "uets")) == {"Ayşe Açık", "Veli KapalıUyap"}


@pytest.mark.parametrize("role", list(User.Role))
def test_every_role_sees_the_lawyer_list(role):
    person()
    viewer = User.objects.create_user(username=f"izleyen-{role}", role=role)
    indicator = portal_status.portal_indicator(viewer)
    assert people(indicator, "uyap") == {"Ayşe Avukat": "pasif"}


def test_pair_link_only_for_admin_without_connection():
    owner = admin()
    lawyer, _ = person()
    assert portal_status.portal_indicator(owner)["can_pair"] is True
    assert portal_status.portal_indicator(lawyer)["can_pair"] is False
    connect(owner)
    assert portal_status.portal_indicator(owner)["can_pair"] is False


def test_indicator_view_renders_names_for_logged_in_user_and_requires_login():
    person()
    user = User.objects.create_user(username="sekreter", role=User.Role.SECRETARY)
    client = Client()
    assert client.get(reverse("portal_indicator")).status_code == 302
    client.force_login(user)
    response = client.get(reverse("portal_indicator"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "UYAP" in html and "UETS" in html and "Ayşe Avukat" in html


def test_topbar_contains_indicator_on_regular_pages():
    user = User.objects.create_user(username="kullanici", role=User.Role.LAWYER)
    client = Client()
    client.force_login(user)
    html = client.get(reverse("cases:list")).content.decode()
    assert 'id="portal-indicator"' in html
