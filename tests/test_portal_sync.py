import base64
import hashlib
import json

import pytest
from django.db import connection
from django.test import Client, override_settings

from apps.accounts.models import User
from apps.imports.models import (
    PortalCase,
    PortalConnection,
    PortalLawyerAccess,
    PortalNotice,
    PortalNoticeDocument,
)


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_only_paired_local_extension_can_import_notice(monkeypatch, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    user = User.objects.create_user(username="yonetici", role=User.Role.ADMIN)
    PortalLawyerAccess.objects.create(user=user, identity_number="10000000146", uets_enabled=True)
    client = Client()
    client.force_login(user)
    paired = client.post("/portal-inceleme/baglanti/")
    assert paired.status_code == 200
    key = paired.context["pair_key"]
    assert PortalConnection.objects.get().key_hash == hashlib.sha256(key.encode()).hexdigest()
    client.logout()
    body = {
        "type": "notice",
        "identity": "10000000146",
        "list": {"id": "ornek", "subject": "Örnek"},
        "details": {
            "metin": "Örnek içerik",
            "ek": {"onceki": "bilgi"},
            "password": "örnek",
            "GuvenlikKodu": "örnek",
        },
        "document": {
            "partId": "parca",
            "content": base64.b64encode(b"%PDF-1.4\nornek").decode(),
        },
    }
    path = "/portal-inceleme/eklentiden-al/"
    payload = json.dumps(body)
    assert client.post(path, payload, content_type="application/json").status_code == 403
    assert (
        client.post(
            path, payload, content_type="application/json", HTTP_AUTHORIZATION="Bearer yanlis"
        ).status_code
        == 403
    )
    assert (
        client.post(
            path,
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
            REMOTE_ADDR="192.0.2.1",
        ).status_code
        == 404
    )
    for _ in range(2):
        response = client.post(
            path, payload, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}"
        )
        assert response.status_code == 200
    assert PortalNotice.objects.count() == 1
    assert PortalNoticeDocument.objects.count() == 1
    assert "password" not in PortalNotice.objects.get().data["ayrinti"]
    assert "GuvenlikKodu" not in PortalNotice.objects.get().data["ayrinti"]
    body["list"]["status"] = "read"
    body["details"] = {"ek": {"yeni": "bilgi"}}
    body["document"] = {
        "partId": "ikinci",
        "name": "ornek.udf",
        "content": base64.b64encode(b"ornek belge").decode(),
    }
    response = client.post(
        path, json.dumps(body), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}"
    )
    assert response.status_code == 200
    assert PortalNotice.objects.get().read is True
    assert PortalNotice.objects.get().data["ayrinti"]["metin"] == "Örnek içerik"
    assert PortalNotice.objects.get().data["ayrinti"]["ek"] == {"onceki": "bilgi", "yeni": "bilgi"}
    assert PortalNoticeDocument.objects.count() == 2
    document = PortalNoticeDocument.objects.get(source_part="ikinci")
    assert document.original_name.endswith(".udf")
    client.force_login(user)
    detail = client.get(f"/portal-inceleme/tebligat/{PortalNotice.objects.get().pk}/")
    assert detail.status_code == 200
    assert "Örnek" in detail.content.decode()
    assert "ornek.udf" in detail.content.decode()
    download = client.get(f"/portal-inceleme/tebligat-belgesi/{document.pk}/")
    assert download.status_code == 200
    assert download.headers["Content-Disposition"].startswith("attachment;")
    assert b"".join(download.streaming_content) == b"ornek belge"
    assert client.delete(path, HTTP_AUTHORIZATION=f"Bearer {key}").status_code == 405


@pytest.mark.django_db
@override_settings(DEBUG=True, PORTAL_UYAP_AUTOMATION_ENABLED=True)
def test_import_rejects_unapproved_portal_operations(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    user = User.objects.create_user(username="yonetici", role=User.Role.ADMIN)
    key = "ornek-baglanti"
    PortalConnection.objects.create(owner=user, key_hash=hashlib.sha256(key.encode()).hexdigest())
    PortalLawyerAccess.objects.create(user=user, identity_number="10000000146", uyap_enabled=True)
    response = Client().post(
        "/portal-inceleme/eklentiden-al/",
        json.dumps(
            {
                "type": "uyap",
                "identity": "10000000146",
                "captures": [{"source": "UYAP", "path": "/sil.ajx"}],
            }
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {key}",
    )
    assert response.status_code == 400
    item = {
        "source": "UYAP",
        "path": "/search_phrase_detayli.ajx",
        "data": {
            "kategori": "Hukuk",
            "sonuc": [[{"birimAdi": "Örnek Mahkeme", "dosyaNo": "2026/1", "dosyaId": "a"}], 1],
        },
    }
    for _ in range(2):
        response = Client().post(
            "/portal-inceleme/eklentiden-al/",
            json.dumps({"type": "uyap", "identity": "10000000146", "captures": [item]}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )
        assert response.status_code == 200
    assert PortalCase.objects.count() == 1


@pytest.mark.django_db
@override_settings(DEBUG=True, PORTAL_UYAP_AUTOMATION_ENABLED=False)
def test_uyap_automatic_import_is_disabled_by_default(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    user = User.objects.create_user(username="yonetici", role=User.Role.ADMIN)
    key = "ornek-baglanti"
    PortalConnection.objects.create(owner=user, key_hash=hashlib.sha256(key.encode()).hexdigest())
    PortalLawyerAccess.objects.create(user=user, identity_number="10000000146", uyap_enabled=True)
    response = Client().post(
        "/portal-inceleme/eklentiden-al/",
        json.dumps({"type": "uyap", "identity": "10000000146", "captures": []}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {key}",
    )
    assert response.status_code == 403
    assert PortalCase.objects.count() == 0


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_health_only_accepts_paired_local_extension_and_known_states(monkeypatch):
    from django.utils import timezone

    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    owner = User.objects.create_user(username="health-admin", role=User.Role.ADMIN)
    key = "test-health-key"
    conn = PortalConnection.objects.create(
        owner=owner, key_hash=hashlib.sha256(key.encode()).hexdigest()
    )
    client = Client()
    url = "/portal-inceleme/durum/"
    now_ms = int(timezone.now().timestamp() * 1000)
    data = {"uyap": {"status": "durduruldu", "attempted": now_ms}, "uets": {"status": "oturum_yok"}}
    assert client.post(url, json.dumps(data), content_type="application/json").status_code == 403
    assert (
        client.post(
            url,
            json.dumps(data),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
            REMOTE_ADDR="192.0.2.1",
        ).status_code
        == 404
    )
    response = client.post(
        url, json.dumps(data), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {key}"
    )
    assert response.status_code == 200 and response.json()["sync_enabled"] is True
    conn.refresh_from_db()
    assert (
        conn.last_seen is not None
        and conn.uyap_status == "durduruldu"
        and conn.uets_status == "oturum_yok"
    )
    assert conn.uyap_attempt_at is not None and conn.uyap_success_at is None
    before = conn.last_seen
    data["uyap"]["status"] = "taninmayan"
    assert (
        client.post(
            url,
            json.dumps(data),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        ).status_code
        == 400
    )
    conn.refresh_from_db()
    assert conn.last_seen == before
    conn.active = False
    conn.save(update_fields=["active"])
    assert (
        client.post(
            url,
            json.dumps(data),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_only_admin_can_manage_connection_and_individual_permission(client):
    from apps.imports.models import PortalLawyerAccess

    admin = User.objects.create_user(username="health-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="health-lawyer", role=User.Role.LAWYER)
    conn = PortalConnection.objects.create(owner=admin, key_hash="example-digest")
    access = PortalLawyerAccess.objects.create(
        user=lawyer, identity_number="10000000146", uyap_enabled=True
    )
    toggle = f"/portal-inceleme/izin/{access.pk}/uyap/"
    stop = f"/portal-inceleme/baglanti/{conn.pk}/durdur/"
    client.force_login(lawyer)
    client.post(toggle)
    client.post(stop)
    access.refresh_from_db()
    conn.refresh_from_db()
    assert access.uyap_enabled and conn.active
    client.force_login(admin)
    page = client.get("/hesap/ayarlar/?bolum=eklenti").content.decode()
    assert "Henüz durum bilgisi yok" in page and "İzinli" in page
    client.post(toggle)
    access.refresh_from_db()
    assert not access.uyap_enabled and not access.uets_enabled
    assert client.post(f"/portal-inceleme/izin/{access.pk}/other/").status_code == 404
    client.post(stop)
    conn.refresh_from_db()
    assert not conn.active


@pytest.mark.django_db
def test_old_health_is_not_shown_as_live(client):
    from datetime import timedelta

    from django.utils import timezone

    admin = User.objects.create_user(username="stale-health-admin", role=User.Role.ADMIN)
    PortalConnection.objects.create(
        owner=admin,
        key_hash="stale-health-example",
        last_seen=timezone.now() - timedelta(minutes=4),
        uyap_status="tamamlandi",
    )
    client.force_login(admin)
    page = client.get("/hesap/ayarlar/?bolum=eklenti").content.decode()
    assert "Eklentiden haber alınamıyor" in page
    assert "Eklentiden haber alındı" not in page
    assert "hangi avukatın UYAP" in page


@pytest.mark.django_db
@override_settings(DEBUG=True, PORTAL_UYAP_AUTOMATION_ENABLED=True)
def test_data_rejected_without_exact_active_person_and_source_permission(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    admin = User.objects.create_user(username="guard-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="guard-lawyer", role=User.Role.LAWYER)
    access = PortalLawyerAccess.objects.create(
        user=lawyer, identity_number="10000000146", uyap_enabled=True, uets_enabled=False
    )
    key = "guard-test-key"
    PortalConnection.objects.create(owner=admin, key_hash=hashlib.sha256(key.encode()).hexdigest())
    client = Client()
    url = "/portal-inceleme/eklentiden-al/"
    uyap = {
        "type": "uyap",
        "identity": "10000000146",
        "captures": [
            {
                "source": "UYAP",
                "path": "/search_phrase_detayli.ajx",
                "data": {
                    "kategori": "Hukuk",
                    "sonuc": [
                        [{"birimAdi": "Örnek Mahkeme", "dosyaNo": "2026/1", "dosyaId": "fake"}],
                        1,
                    ],
                },
            }
        ],
    }

    def send(body):
        return client.post(
            url,
            json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

    assert send({**uyap, "identity": ""}).status_code == 403
    assert send({**uyap, "identity": "10000000147"}).status_code == 403
    assert (
        send(
            {"type": "notice", "identity": "10000000146", "list": {"id": "fake"}, "details": {}}
        ).status_code
        == 403
    )
    assert not PortalCase.objects.exists() and not PortalNotice.objects.exists()
    assert send(uyap).status_code == 200
    access.uyap_enabled = False
    access.save(update_fields=["uyap_enabled"])
    assert send(uyap).status_code == 403
    access.uyap_enabled = True
    access.save(update_fields=["uyap_enabled"])
    lawyer.is_active = False
    lawyer.save(update_fields=["is_active"])
    assert send(uyap).status_code == 403
    lawyer.is_active = True
    lawyer.role = User.Role.INTERN
    lawyer.save(update_fields=["is_active", "role"])
    assert send(uyap).status_code == 403


@pytest.mark.django_db
@override_settings(DEBUG=True, PORTAL_UYAP_AUTOMATION_ENABLED=True)
def test_portal_name_match_requires_one_active_permitted_lawyer(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    admin = User.objects.create_user(username="name-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(
        username="name-lawyer", first_name="Işıl", last_name="İnci", role=User.Role.LAWYER
    )
    access = PortalLawyerAccess.objects.create(
        user=lawyer, identity_number="10000000146", uyap_enabled=True
    )
    key = "name-test-key"
    PortalConnection.objects.create(owner=admin, key_hash=hashlib.sha256(key.encode()).hexdigest())
    client = Client()
    body = {
        "type": "uyap",
        "lawyer_name": "IŞIL İNCİ",
        "captures": [
            {
                "source": "UYAP",
                "path": "/search_phrase_detayli.ajx",
                "data": {"kategori": "Hukuk", "sonuc": [[], 0]},
            }
        ],
    }

    def send(name):
        return client.post(
            "/portal-inceleme/eklentiden-al/",
            json.dumps({**body, "lawyer_name": name}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

    assert send("IŞIL İNCİ").status_code == 200
    assert send("İŞİL İNCİ").status_code == 403
    assert send("IŞIL İNCİ ").status_code == 403
    access.uyap_enabled = False
    access.save(update_fields=["uyap_enabled"])
    assert send("IŞIL İNCİ").status_code == 403
    access.uyap_enabled = True
    access.save(update_fields=["uyap_enabled"])
    other = User.objects.create_user(username="same-name", first_name="IŞIL", last_name="İNCİ")
    PortalLawyerAccess.objects.create(user=other, identity_number="10000000147", uyap_enabled=True)
    assert send("IŞIL İNCİ").status_code == 403


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_extension_checks_name_against_separate_source_permissions(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    admin = User.objects.create_user(username="check-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="check-lawyer", first_name="Işıl", last_name="İnci")
    PortalLawyerAccess.objects.create(user=lawyer, identity_number="10000000146", uets_enabled=True)
    key = "check-test-key"
    PortalConnection.objects.create(owner=admin, key_hash=hashlib.sha256(key.encode()).hexdigest())
    client = Client()

    def check(name, source, secret=key):
        return client.post(
            "/portal-inceleme/isim-kontrol/",
            json.dumps({"name": name, "source": source}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {secret}",
        )

    assert check("IŞIL İNCİ", "uets").json() == {"ok": True}
    assert check("IŞIL İNCİ", "uyap").json() == {"ok": False}
    assert check("FARKLI KİŞİ", "uets").json() == {"ok": False}
    assert check("IŞIL İNCİ", "uets", "wrong").status_code == 403


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_local_request_allows_office_lan_ips_and_rejects_external(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    admin = User.objects.create_user(username="lan-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="lan-lawyer", first_name="Işıl", last_name="İnci")
    PortalLawyerAccess.objects.create(user=lawyer, identity_number="10000000146", uets_enabled=True)
    key = "lan-test-key"
    PortalConnection.objects.create(owner=admin, key_hash=hashlib.sha256(key.encode()).hexdigest())
    client = Client()

    url = "/portal-inceleme/isim-kontrol/"
    payload = json.dumps({"name": "IŞIL İNCİ", "source": "uets"})
    auth = f"Bearer {key}"

    # Yerel ofis ağı (192.168.x.x, 10.x.x.x) erişebilir
    for lan_ip in ("127.0.0.1", "192.168.1.100", "10.0.0.15", "172.16.5.20"):
        resp = client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=auth,
            REMOTE_ADDR=lan_ip,
        )
        assert resp.status_code == 200, f"{lan_ip} erişebilmeli"
        assert resp.json() == {"ok": True}

    # Dış internet / bilinmeyen IP erişemez (404)
    for ext_ip in ("192.0.2.1", "198.51.100.2", "8.8.8.8"):
        resp = client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=auth,
            REMOTE_ADDR=ext_ip,
        )
        assert resp.status_code == 404, f"{ext_ip} engellenmeli"
