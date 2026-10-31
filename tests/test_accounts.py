import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.accounts.models import User

pytestmark = pytest.mark.django_db

TEST_PIN = "4826"  # yalnızca test için uydurma PIN


@pytest.fixture
def pin_user(db):
    u = User.objects.create_user(
        username="test.kullanici", first_name="Test", last_name="KULLANICI", title="Avukat"
    )
    u.set_password(TEST_PIN)
    u.save()
    return u


def test_login_page_lists_active_users_only(client, pin_user):
    User.objects.create_user(username="pasif", first_name="Pasif", is_active=False)
    r = client.get(reverse("accounts:login"))
    assert list(r.context["users"]) == [pin_user]
    assert 'data-username="test.kullanici"' in r.content.decode()


def test_login_with_pin(client, pin_user):
    r = client.post(
        reverse("accounts:login"), {"username": pin_user.username, "password": TEST_PIN}
    )
    assert r.status_code == 302
    assert r.url == reverse("core:home")


def test_wrong_pin_keeps_user_selected(client, pin_user):
    r = client.post(reverse("accounts:login"), {"username": pin_user.username, "password": "0000"})
    assert r.status_code == 200
    assert "PIN hatalı" in r.content.decode()
    assert r.context["form"]["username"].value() == pin_user.username


def test_pin_change_in_settings(client, pin_user):
    client.force_login(pin_user)
    url = reverse("accounts:settings")
    data = {"section": "pin", "old_pin": TEST_PIN}
    r = client.post(url, {**data, "new_pin": "12a4", "new_pin2": "12a4"})
    assert "new_pin" in r.context["forms"]["pin"].errors
    r = client.post(url, {**data, "new_pin": "1357", "new_pin2": "1357"})
    assert r.status_code == 302
    pin_user.refresh_from_db()
    assert pin_user.check_password("1357")
    # Eski PIN adresi ayarlara yönlenir.
    assert client.get(reverse("accounts:pin_change")).url == "/hesap/ayarlar/?bolum=pin"


def test_profile_settings(client, pin_user):
    client.force_login(pin_user)
    r = client.post(
        reverse("accounts:settings"),
        {
            "section": "profil",
            "first_name": "Yeni",
            "last_name": "AD",
            "email": "",
            "phone": "",
            "theme": "dark",
            "page_size": 50,
        },
    )
    assert r.status_code == 302
    pin_user.refresh_from_db()
    assert (pin_user.first_name, pin_user.theme, pin_user.page_size) == ("Yeni", "dark", 50)


def test_office_and_calendar_settings_admin_only(client, pin_user):
    from apps.office.models import OfficeSettings

    client.force_login(pin_user)  # avukat rolü
    url = reverse("accounts:settings")
    assert "ofis" not in client.get(url).context["forms"]
    r = client.post(url, {"section": "takvim", "calendar_ics_url": "https://x.test/a.ics"})
    assert r.status_code == 403

    pin_user.role = User.Role.ADMIN
    pin_user.save()
    secret = "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics"
    client.post(url, {"section": "takvim", "calendar_ics_url": secret})
    assert OfficeSettings.load().calendar_ics_url == secret
    # Boş gönderim mevcut adresi korur, adres sayfada görünmez.
    client.post(url, {"section": "takvim", "calendar_ics_url": ""})
    assert OfficeSettings.load().calendar_ics_url == secret
    assert secret not in client.get(url, {"bolum": "takvim"}).content.decode()
    client.post(url, {"section": "takvim", "calendar_ics_url": "", "clear": "on"})
    assert OfficeSettings.load().calendar_ics_url == ""


def test_setup_office_users():
    call_command("setup_office_users", pin=TEST_PIN)
    assert User.objects.count() == 6
    admin = User.objects.get(username="ali.samet.ozkurt")
    assert admin.is_office_admin and admin.is_superuser
    assert admin.check_password(TEST_PIN)
    assert admin.initials == "AÖ"
    assert list(User.objects.values_list("title", flat=True))[:2] == [
        "Yönetici Avukat",
        "Koordinatör Avukat",
    ]
    # Tekrar çalıştırmak mevcut PIN'i değiştirmez.
    admin.set_password("999999")
    admin.save()
    call_command("setup_office_users", pin=TEST_PIN)
    admin.refresh_from_db()
    assert admin.check_password("999999")


@pytest.mark.parametrize("pin", ["12", "12345", "12a4"])
def test_setup_rejects_invalid_pin(pin):
    # PIN tam 4 rakam olmalı (giriş ekranı 4. rakamda otomatik gönderir).
    with pytest.raises(CommandError):
        call_command("setup_office_users", pin=pin)
