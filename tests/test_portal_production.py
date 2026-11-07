import base64
import json

import pytest
from django.test import Client, override_settings

from apps.accounts.models import User
from apps.imports.models import PortalConnection, PortalLawyerAccess, PortalNotice

pytestmark = pytest.mark.django_db

INGEST = "/portal-inceleme/eklentiden-al/"
HEALTH = "/portal-inceleme/durum/"
NAME_CHECK = "/portal-inceleme/isim-kontrol/"


def paired(role=User.Role.ADMIN, username="yonetici", identity="10000000146", **access):
    user = User.objects.create_user(username=username, role=role)
    values = {"uyap_enabled": True, "uets_enabled": True, **access}
    PortalLawyerAccess.objects.create(user=user, identity_number=identity, **values)
    client = Client()
    client.force_login(user)
    response = client.post("/portal-inceleme/baglanti/")
    return client, user, response


@override_settings(DEBUG=False)
def test_pairing_works_without_debug():
    client, _, response = paired()
    assert response.status_code == 200
    assert PortalConnection.objects.count() == 1
    assert response.context["pair_key"]


@override_settings(DEBUG=False)
def test_extension_can_send_notice_health_and_name_check_without_debug():
    client, _, response = paired()
    key = response.context["pair_key"]
    auth = {"HTTP_AUTHORIZATION": f"Bearer {key}"}
    anonymous = Client()
    body = {
        "type": "notice",
        "identity": "10000000146",
        "list": {"id": "uretim", "subject": "Üretim"},
        "details": {"metin": "içerik"},
        "document": {"partId": "p1", "content": base64.b64encode(b"%PDF-1.4\nornek").decode()},
    }
    ok = anonymous.post(INGEST, json.dumps(body), content_type="application/json", **auth)
    assert ok.status_code == 200
    assert PortalNotice.objects.count() == 1

    health = {"uyap": {"status": "tamamlandi"}, "uets": {"status": "bekliyor"}}
    status = anonymous.post(HEALTH, json.dumps(health), content_type="application/json", **auth)
    assert status.status_code == 200
    connection = PortalConnection.objects.get()
    assert connection.uyap_status == "tamamlandi" and connection.last_seen


@override_settings(DEBUG=False)
def test_non_admin_or_unpaired_key_is_still_rejected_without_debug():
    anonymous = Client()
    payload = json.dumps({"type": "notice", "identity": "10000000146", "list": {"id": "x"}})
    wrong = anonymous.post(
        INGEST, payload, content_type="application/json", HTTP_AUTHORIZATION="Bearer yanlis"
    )
    assert wrong.status_code == 403
    client, user, response = paired()
    key = response.context["pair_key"]
    user.role = User.Role.LAWYER
    user.save()
    rejected = anonymous.post(
        INGEST, payload, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}"
    )
    assert rejected.status_code in (400, 403)
    assert PortalNotice.objects.count() == 0


@override_settings(DEBUG=False)
@pytest.mark.parametrize(
    "role",
    [
        User.Role.SENIOR,
        User.Role.LAWYER,
        User.Role.INTERN,
        User.Role.PARALEGAL,
        User.Role.SECRETARY,
    ],
)
def test_only_admin_can_pair_the_extension(role):
    # Eklenti yalnızca ana (sunucu) bilgisayarda yönetici tarafından eşleştirilir.
    user = User.objects.create_user(username=f"kullanici-{role}", role=role)
    PortalLawyerAccess.objects.create(
        user=user, identity_number="10000000148", uyap_enabled=True, uets_enabled=True
    )
    client = Client()
    client.force_login(user)
    assert client.get("/portal-inceleme/baglanti/").status_code == 404
    assert client.post("/portal-inceleme/baglanti/").status_code == 404
    assert PortalConnection.objects.count() == 0
