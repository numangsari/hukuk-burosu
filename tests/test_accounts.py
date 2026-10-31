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


def test_pin_change(client, pin_user):
    client.force_login(pin_user)
    url = reverse("accounts:pin_change")
    r = client.post(url, {"old_pin": TEST_PIN, "new_pin": "12a4", "new_pin2": "12a4"})
    assert "new_pin" in r.context["form"].errors
    r = client.post(url, {"old_pin": TEST_PIN, "new_pin": "135790", "new_pin2": "135790"})
    assert r.status_code == 302
    pin_user.refresh_from_db()
    assert pin_user.check_password("135790")


def test_setup_office_users():
    call_command("setup_office_users", pin=TEST_PIN)
    assert User.objects.count() == 5
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


def test_setup_rejects_invalid_pin():
    with pytest.raises(CommandError):
        call_command("setup_office_users", pin="12")
