import datetime as dt
import json

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.imports import portal_status
from apps.imports.models import PortalConnection, PortalLawyerAccess

pytestmark = pytest.mark.django_db

HEALTH = "/portal-inceleme/durum/"


def paired_client():
    admin = User.objects.create_user(username="oturum-yonetici", role=User.Role.ADMIN)
    client = Client()
    client.force_login(admin)
    key = client.post("/portal-inceleme/baglanti/").context["pair_key"]
    return admin, {"HTTP_AUTHORIZATION": f"Bearer {key}"}


def lawyer(first="Ayşe", last="Avukat", **access):
    user = User.objects.create_user(
        username=f"{first}-{last}".lower(), first_name=first, last_name=last, role=User.Role.LAWYER
    )
    values = {"uyap_enabled": True, "uets_enabled": True, **access}
    record = PortalLawyerAccess.objects.create(
        user=user, identity_number=f"2000000{User.objects.count():04d}", **values
    )
    return user, record


def millis(delta=dt.timedelta()):
    return int((timezone.now() - delta).timestamp() * 1000)


def send(auth, uyap=None, uets=None):
    body = {
        "uyap": {"status": "tamamlandi", **(uyap or {})},
        "uets": {"status": "tamamlandi", **(uets or {})},
    }
    return Client().post(HEALTH, json.dumps(body), content_type="application/json", **auth)


def test_health_stores_session_state_per_source():
    _, auth = paired_client()
    response = send(
        auth,
        uyap={"session": {"ok": True, "at": millis()}},
        uets={"session": {"ok": False, "at": millis()}},
    )
    assert response.status_code == 200
    connection = PortalConnection.objects.get()
    assert connection.uyap_session_ok is True and connection.uyap_session_at
    assert connection.uets_session_ok is False and connection.uets_session_at


def test_health_without_session_keeps_old_values_null():
    _, auth = paired_client()
    assert send(auth).status_code == 200
    connection = PortalConnection.objects.get()
    assert connection.uyap_session_ok is None and connection.uyap_session_at is None
    assert connection.uyap_account is None and connection.uets_account is None


@pytest.mark.parametrize(
    "session",
    [
        {"ok": "evet", "at": 1},
        {"ok": True, "at": "dün"},
        {"ok": True},
        "açık",
        {"ok": True, "at": True},
    ],
)
def test_health_ignores_malformed_session(session):
    _, auth = paired_client()
    assert send(auth, uyap={"session": session}).status_code == 200
    connection = PortalConnection.objects.get()
    assert connection.uyap_session_ok is None


def test_health_rejects_future_session_timestamp():
    _, auth = paired_client()
    future = millis(dt.timedelta(minutes=-30))
    assert send(auth, uyap={"session": {"ok": True, "at": future}}).status_code == 200
    assert PortalConnection.objects.get().uyap_session_ok is None


def test_open_account_name_is_matched_to_the_permitted_lawyer():
    _, auth = paired_client()
    _, access = lawyer("Ayşe", "Avukat")
    send(auth, uyap={"session": {"ok": True, "at": millis(), "name": "AYŞE AVUKAT"}})
    connection = PortalConnection.objects.get()
    assert connection.uyap_account == access
    assert connection.uets_account is None


def test_unknown_or_unpermitted_account_name_is_not_attributed():
    _, auth = paired_client()
    lawyer("Veli", "Avukat", uyap_enabled=False)
    send(auth, uyap={"session": {"ok": True, "at": millis(), "name": "Veli Avukat"}})
    assert PortalConnection.objects.get().uyap_account is None
    send(auth, uyap={"session": {"ok": True, "at": millis(), "name": "Tanımsız Kişi"}})
    assert PortalConnection.objects.get().uyap_account is None


def test_account_is_cleared_when_another_account_or_no_name_is_reported():
    _, auth = paired_client()
    _, access = lawyer("Ayşe", "Avukat")
    send(auth, uyap={"session": {"ok": True, "at": millis(), "name": "Ayşe Avukat"}})
    assert PortalConnection.objects.get().uyap_account == access
    send(auth, uyap={"session": {"ok": True, "at": millis()}})
    assert PortalConnection.objects.get().uyap_account is None


@pytest.mark.parametrize("name", [5, "x" * 201, ["Ayşe Avukat"]])
def test_malformed_account_name_is_ignored(name):
    _, auth = paired_client()
    lawyer("Ayşe", "Avukat")
    assert (
        send(auth, uyap={"session": {"ok": True, "at": millis(), "name": name}}).status_code == 200
    )
    assert PortalConnection.objects.get().uyap_account is None


def make(owner, **values):
    return PortalConnection.objects.create(
        key_hash=f"oturum-{PortalConnection.objects.count()}",
        owner=owner,
        last_seen=timezone.now(),
        **values,
    )


def state(connection, source="uyap"):
    return portal_status.connection_state(connection, source, timezone.now())


def test_fresh_open_session_is_active_even_when_last_scan_said_no_session():
    owner, _ = paired_client()
    connection = make(
        owner, uyap_status="oturum_yok", uyap_session_ok=True, uyap_session_at=timezone.now()
    )
    assert state(connection) == "aktif"


def test_fresh_closed_session_is_passive_even_when_last_scan_was_good():
    owner, _ = paired_client()
    connection = make(
        owner, uyap_status="tamamlandi", uyap_session_ok=False, uyap_session_at=timezone.now()
    )
    assert state(connection) == "pasif"


@pytest.mark.parametrize("status", ["izin_yok", "sunucu_yok"])
def test_open_session_but_blocked_transfer_is_passive(status):
    owner, _ = paired_client()
    connection = make(
        owner, uyap_status=status, uyap_session_ok=True, uyap_session_at=timezone.now()
    )
    assert state(connection) == "pasif"


def test_stale_session_info_falls_back_to_scan_status():
    owner, _ = paired_client()
    old = timezone.now() - dt.timedelta(minutes=30)
    good_scan = make(owner, uyap_status="tamamlandi", uyap_session_ok=False, uyap_session_at=old)
    bad_scan = make(owner, uyap_status="oturum_yok", uyap_session_ok=True, uyap_session_at=old)
    assert state(good_scan) == "aktif"
    assert state(bad_scan) == "pasif"


def reason(connection, source="uyap"):
    return portal_status.inactive_reason(connection, source, timezone.now())


def test_reason_is_empty_when_active():
    owner, _ = paired_client()
    connection = make(owner, uyap_status="tamamlandi")
    assert reason(connection) == ""


@pytest.mark.parametrize(
    ("status", "text"),
    [
        ("izin_yok", "izin verilmemiş"),
        ("sunucu_yok", "sunucuya ulaşamadı"),
        ("sekme_yok", "Sekme açık değil"),
        ("oturum_yok", "Oturum kapalı"),
    ],
)
def test_reason_names_the_blocking_scan_state(status, text):
    owner, _ = paired_client()
    connection = make(owner, uyap_status=status)
    assert text in reason(connection)


def test_reason_for_closed_session_and_silent_extension():
    owner, _ = paired_client()
    closed = make(
        owner, uyap_status="tamamlandi", uyap_session_ok=False, uyap_session_at=timezone.now()
    )
    assert "Oturum kapalı" in reason(closed)
    silent = make(owner, uyap_status="tamamlandi")
    silent.last_seen = timezone.now() - dt.timedelta(minutes=10)
    assert "yanıt vermiyor" in reason(silent)
