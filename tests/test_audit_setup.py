"""Kurulu ofiste anonim yönetici oluşturulmasını engelleyen regresyon."""

import pytest
from django.urls import reverse

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_inactive_accounts_do_not_reopen_setup(client, admin_user):
    admin_user.is_active = False
    admin_user.save(update_fields=["is_active"])
    assert client.get(reverse("accounts:login")).status_code == 200
    for method in (client.get, client.post):
        response = method(
            reverse("accounts:initial_setup"),
            {
                "office_name": "Test",
                "first_name": "Test",
                "last_name": "Yönetici",
                "pin": "2580",
                "pin2": "2580",
            },
        )
        assert response.status_code == 302
        assert response.url == reverse("accounts:login")
    assert User.objects.count() == 1
