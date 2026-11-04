import time

import pytest
from django.core.management import call_command
from django.test import Client as HttpClient
from django.urls import reverse

from apps.accounts.models import User
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db
PIN = "4826"  # yalnızca test


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def test_setup_users_start_pin_is_optional_to_change():
    call_command("setup_office_users", pin=PIN)
    u = User.objects.get(username="avukat.ayse")
    assert not u.must_change_pin
    assert login(u).get(reverse("clients:list")).status_code == 200


def test_must_change_pin_then_released():
    call_command("setup_office_users", pin=PIN)
    u = User.objects.get(username="avukat.ayse")
    u.must_change_pin = True
    u.save()
    c = login(u)
    r = c.get(reverse("clients:list"))
    assert r.status_code == 302 and r.url == "/hesap/ayarlar/?bolum=pin"
    assert c.get(reverse("accounts:settings"), {"bolum": "pin"}).status_code == 200
    # Aynı PIN kabul edilmez
    r = c.post(
        reverse("accounts:settings"),
        {"section": "pin", "old_pin": PIN, "new_pin": PIN, "new_pin2": PIN},
    )
    assert "new_pin" in r.context["forms"]["pin"].errors
    c.post(
        reverse("accounts:settings"),
        {"section": "pin", "old_pin": PIN, "new_pin": "5931", "new_pin2": "5931"},
    )
    u.refresh_from_db()
    assert not u.must_change_pin
    assert c.get(reverse("clients:list")).status_code == 200


def test_htmx_requests_get_hx_redirect(lawyer):
    lawyer.must_change_pin = True
    lawyer.save()
    r = login(lawyer).get(reverse("clients:list"), HTTP_HX_REQUEST="true")
    assert r.status_code == 204 and r["HX-Redirect"] == "/hesap/ayarlar/?bolum=pin"


def test_admin_set_pin_is_temporary_for_others(admin_user, lawyer):
    c = login(admin_user)
    data = {"section": "kullanicilar", "user_id": lawyer.pk, "first_name": "A", "last_name": "B", "role": "lawyer",
            "title": "", "order": 0, "is_active": "on", "pin": "7777"}  # fmt: skip
    c.post(reverse("accounts:settings"), data)
    lawyer.refresh_from_db()
    assert lawyer.must_change_pin and lawyer.check_password("7777")


def test_idle_timeout_logs_out(lawyer):
    office = OfficeSettings.load()
    office.idle_minutes = 30
    office.save()
    c = login(lawyer)
    assert c.get(reverse("core:home")).status_code == 200
    session = c.session
    session["last_seen"] = int(time.time()) - 31 * 60
    session.save()
    r = c.get(reverse("core:home"))
    assert r.status_code == 302 and "zaman_asimi=1" in r.url
    assert c.get(reverse("core:home")).status_code == 302  # oturum kapandı
    assert "oturum kapatıldı" in HttpClient().get(r.url).content.decode()


def test_idle_timeout_disabled_with_zero(lawyer):
    office = OfficeSettings.load()
    office.idle_minutes = 0
    office.save()
    c = login(lawyer)
    c.get(reverse("core:home"))
    session = c.session
    session["last_seen"] = int(time.time()) - 10 * 3600
    session.save()
    assert c.get(reverse("core:home")).status_code == 200
