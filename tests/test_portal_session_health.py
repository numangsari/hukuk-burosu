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
    user = User.objects.create_user(username="oturum-avukat", role=User.Role.LAWYER)
    PortalLawyerAccess.objects.create(
        user=user, identity_number="10000000146", uyap_enabled=True, uets_enabled=True
    )
    client = Client()
    client.force_login(user)
    key = client.post("/portal-inceleme/baglanti/").context["pair_key"]
    return user, {"HTTP_AUTHORIZATION": f"Bearer {key}"}


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


def make(user, **values):
    return PortalConnection.objects.create(
        key_hash=f"oturum-{PortalConnection.objects.count()}",
        owner=user,
        last_seen=timezone.now(),
        **values,
    )


def uyap_state(user):
    indicator = portal_status.portal_indicator(user)
    return next(row["state"] for row in indicator["sources"] if row["key"] == "uyap")


def lawyer():
    return User.objects.create_user(username="gosterge-avukat", role=User.Role.LAWYER)


def test_fresh_open_session_is_active_even_when_last_scan_said_no_session():
    user = lawyer()
    make(user, uyap_status="oturum_yok", uyap_session_ok=True, uyap_session_at=timezone.now())
    assert uyap_state(user) == "aktif"


def test_fresh_closed_session_is_passive_even_when_last_scan_was_good():
    user = lawyer()
    make(user, uyap_status="tamamlandi", uyap_session_ok=False, uyap_session_at=timezone.now())
    assert uyap_state(user) == "pasif"


@pytest.mark.parametrize("status", ["izin_yok", "sunucu_yok"])
def test_open_session_but_blocked_transfer_is_passive(status):
    user = lawyer()
    make(user, uyap_status=status, uyap_session_ok=True, uyap_session_at=timezone.now())
    assert uyap_state(user) == "pasif"


def test_stale_session_info_falls_back_to_scan_status():
    user = lawyer()
    old = timezone.now() - dt.timedelta(minutes=30)
    good_scan = make(user, uyap_status="tamamlandi", uyap_session_ok=False, uyap_session_at=old)
    other = User.objects.create_user(username="eski-avukat-2", role=User.Role.LAWYER)
    bad_scan = make(other, uyap_status="oturum_yok", uyap_session_ok=True, uyap_session_at=old)
    now = timezone.now()
    assert portal_status.connection_state(good_scan, "uyap", now) == "aktif"
    assert portal_status.connection_state(bad_scan, "uyap", now) == "pasif"
