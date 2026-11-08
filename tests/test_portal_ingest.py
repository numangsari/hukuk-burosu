import json

import pytest
from django.db import connection
from django.test import Client as HttpClient
from django.test import override_settings

from apps.accounts.models import User
from apps.cases import services, stages
from apps.cases.forms import CaseStageForm
from apps.cases.models import Case, CaseType
from apps.clients.models import Client
from apps.imports.models import PortalCapture, PortalCase, PortalNotice
from apps.imports.portal_ingest import (
    import_captures,
    import_files,
    import_notice_pdf,
    kind_for,
    represented,
)


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_import_preserves_source_without_creating_office_records(tmp_path, monkeypatch):
    user = User.objects.create_user(
        username="ornek", first_name="Deneme", last_name="Avukat", role=User.Role.ADMIN
    )
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    rows = [
        {
            "birimAdi": "Örnek Mahkeme",
            "dosyaNo": "2026/1",
            "dosyaTur": "Hukuk Dava Dosyası",
            "dosyaDurum": "Açık",
            "dosyaId": "ornek-a",
        },
        {
            "birimAdi": "Örnek Mahkeme",
            "dosyaNo": "2026/2",
            "dosyaTur": "Hukuk Dava Dosyası",
            "dosyaDurum": "Açık",
            "dosyaId": "ornek-b",
        },
    ]
    captures = [
        {
            "source": "UYAP",
            "path": "/search_phrase_detayli.ajx",
            "data": {"kategori": "Hukuk", "sonuc": [rows, 2]},
        },
        {
            "source": "UYAP",
            "path": "/dosya_taraf_bilgileri_brd.ajx",
            "data": {
                "dosyaId": "ornek-a",
                "sonuc": [
                    {
                        "adi": "ÖRNEK KURUM",
                        "kisiKurum": "Kurum",
                        "rol": "Davacı",
                        "vekil": "[DENEME AVUKAT]",
                    },
                    {"adi": "ÖRNEK KARŞI TARAF", "kisiKurum": "Kişi", "rol": "Davalı"},
                ],
            },
        },
        {
            "source": "UYAP",
            "path": "/avukat_durusma_sorgula_brd.ajx",
            "data": [
                {
                    "dosyaId": "ornek-a",
                    "dosyaNo": "2026/1",
                    "yerelBirimAd": "Örnek Mahkeme",
                    "dosyaTurKodAciklama": "Hukuk Dava Dosyası",
                    "tarihSaat": "2026-11-03 10:00:00",
                    "token": "saklanmamali",
                }
            ],
        },
        {
            "source": "UETS",
            "path": "/v1/messages",
            "data": [
                {
                    "id": 123,
                    "subject": "Örnek ileti",
                    "sender_name": "Örnek kurum",
                    "inserttime": 1700000000,
                    "status": "read",
                    "access_token": "saklanmamali",
                }
            ],
        },
        {"source": "UYAP", "path": "/getNatsParameters.ajx", "data": {"pass": "saklanmamali"}},
    ]
    path = tmp_path / "ornek.json"
    path.write_text(json.dumps(captures), encoding="utf-8")

    initial_clients = Client.objects.count()
    result = import_files([path], user)
    assert result["kaynak_dosya"] == 2
    assert result["olusan_dosya"] == 0
    assert result["tebligat"] == 1
    assert Client.objects.count() == initial_clients
    assert Case.objects.count() == 0
    assert PortalCase.objects.filter(case__isnull=True).count() == 2
    assert not PortalCapture.objects.filter(path__icontains="nats").exists()
    assert "saklanmamali" not in json.dumps(
        list(PortalCapture.objects.values_list("data", flat=True))
    )
    assert import_files([path], user) == result
    web = HttpClient()
    web.force_login(user)
    assert "Örnek ileti" in web.get("/tebligatlar/", {"durum": "all"}).content.decode()
    record = PortalCase.objects.get(number="2026/1")
    assert "ÖRNEK KARŞI TARAF" in web.get(f"/portal-inceleme/{record.pk}/").content.decode()


@pytest.mark.django_db
def test_explicit_other_lawyer_is_not_overridden_by_hearing_flag():
    user = User.objects.create_user(
        username="ornek", first_name="Deneme", last_name="Avukat", role=User.Role.ADMIN
    )
    parties = [{"adi": "ÖRNEK KURUM", "vekil": "[BAŞKA AVUKAT]"}]
    hearing = [{"isim": "ÖRNEK MÜDÜRLÜĞÜ", "isVekil": True}]
    assert represented(parties, hearing, user) == []


def test_investigation_is_not_confused_with_criminal_trial():
    assert kind_for({"dosyaTur": "Soruşturma Dosyası"}, "Ceza") == "investigation"


def test_sales_office_is_a_separate_type_without_stages():
    assert kind_for({}, "Satış Memurluğu") == CaseType.SALES_OFFICE
    assert stages.open_stages(CaseType.SALES_OFFICE) == []
    assert stages.default_stage(CaseType.SALES_OFFICE) == ""


@pytest.mark.django_db
def test_sales_office_case_can_reopen_without_stage():
    user = User.objects.create_user(username="ornek", role=User.Role.ADMIN)
    client = Client.objects.create(
        kind="company", title="Örnek", responsible_lawyer=user, responsible_intern=user
    )
    case = Case.objects.create(
        client=client,
        case_type=CaseType.SALES_OFFICE,
        responsible_lawyer=user,
        responsible_intern=user,
    )
    assert case.stage == ""
    case.status = "closed"
    case.save()
    assert CaseStageForm({}, case=case).is_valid()
    reopened = services.reopen_case(case, "", user)
    assert reopened.is_open and reopened.stage == ""


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_direct_capture_import_uses_the_same_safety_rules(monkeypatch):
    user = User.objects.create_user(username="ornek", role=User.Role.ADMIN)
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    captures = [
        {"source": "UETS", "path": "/v1/messages", "data": [{"id": 1, "subject": "Örnek"}]},
        {"source": "UETS", "path": "/login", "data": {"password": "örnek"}},
    ]
    import_captures(captures, user)
    import_captures(captures, user)
    assert PortalNotice.objects.count() == 1
    assert PortalCapture.objects.count() == 1


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_notice_pdf_is_kept_once_and_office_users_can_access_it(tmp_path, monkeypatch, settings):
    settings.MEDIA_ROOT = tmp_path
    user = User.objects.create_user(username="yonetici", role=User.Role.ADMIN)
    other = User.objects.create_user(username="diger", role=User.Role.INTERN)
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    notice = PortalNotice.objects.create(fingerprint="a" * 64)
    content = b"%PDF-1.4\n ornek belge"
    document = import_notice_pdf(notice, "parca-1", content, user)
    assert import_notice_pdf(notice, "parca-1", content, user).pk == document.pk
    with pytest.raises(ValueError):
        import_notice_pdf(notice, "parca-2", b"pdf degil", user)
    client = HttpClient()
    client.force_login(user)
    response = client.get(f"/portal-inceleme/tebligat-belgesi/{document.pk}/")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == content
    client.force_login(other)
    assert client.get(f"/portal-inceleme/tebligat-belgesi/{document.pk}/").status_code == 200
    client.logout()
    assert client.get(f"/portal-inceleme/tebligat-belgesi/{document.pk}/").status_code != 200


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_later_partial_import_keeps_previous_case_details(tmp_path, monkeypatch):
    user = User.objects.create_user(username="ornek", role=User.Role.ADMIN)
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    rows = [{"birimAdi": "Örnek Mahkeme", "dosyaNo": "2026/1", "dosyaId": "ornek"}]
    listing = {
        "source": "UYAP",
        "path": "/search_phrase_detayli.ajx",
        "data": {"kategori": "Hukuk", "sonuc": [rows, 1]},
    }
    details = {
        "source": "UYAP",
        "path": "/dosyaAyrintiBilgileri_brd.ajx",
        "data": {"dosyaId": "ornek", "sonuc": {"davaninKonusu": "Örnek"}},
    }
    path = tmp_path / "ornek.json"
    path.write_text(json.dumps([listing, details]), encoding="utf-8")
    import_files([path], user)
    path.write_text(json.dumps([listing]), encoding="utf-8")
    import_files([path], user)
    assert PortalCase.objects.get().data["ayrintilar"] == [{"davaninKonusu": "Örnek"}]


@pytest.mark.django_db
@override_settings(DEBUG=True)
@pytest.mark.parametrize("same_client", [True, False])
def test_existing_case_is_not_automatically_linked(monkeypatch, same_client):
    user = User.objects.create_user(
        username="yonetici", first_name="Deneme", last_name="Avukat", role=User.Role.ADMIN
    )
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    client = Client.objects.create(
        kind="company",
        title="ÖRNEK KURUM" if same_client else "BAŞKA KURUM",
        responsible_lawyer=user,
        responsible_intern=user,
        created_by=user,
    )
    existing = Case.objects.create(
        client=client,
        case_type="civil",
        official_no="2026/1",
        authority="Örnek Mahkeme",
        subject="Önceden yazılmış konu",
        responsible_lawyer=user,
        responsible_intern=user,
        created_by=user,
    )
    existing.refresh_from_db()
    original_subject = existing.subject
    captures = [
        {
            "source": "UYAP",
            "path": "/search_phrase_detayli.ajx",
            "data": {
                "kategori": "Hukuk",
                "sonuc": [[{"birimAdi": "Örnek Mahkeme", "dosyaNo": "2026/1", "dosyaId": "a"}], 1],
            },
        },
        {
            "source": "UYAP",
            "path": "/dosya_taraf_bilgileri_brd.ajx",
            "data": {
                "dosyaId": "a",
                "sonuc": [
                    {
                        "adi": "ÖRNEK KURUM",
                        "kisiKurum": "Kurum",
                        "rol": "Davacı",
                        "vekil": "[DENEME AVUKAT]",
                    }
                ],
            },
        },
    ]
    import_captures(captures, user)
    assert Case.objects.count() == 1
    assert PortalCase.objects.get().case_id is None
    existing.refresh_from_db()
    assert existing.subject == original_subject


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_same_named_parties_in_different_cases_are_not_merged(tmp_path, monkeypatch):
    user = User.objects.create_user(
        username="ornek", first_name="Deneme", last_name="Avukat", role=User.Role.ADMIN
    )
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    rows = [
        {
            "birimAdi": "Örnek Mahkeme",
            "dosyaNo": f"2026/{number}",
            "dosyaTur": "Hukuk Dava Dosyası",
            "dosyaDurum": "Açık",
            "dosyaId": str(number),
        }
        for number in (1, 2)
    ]
    parties = [
        {"adi": "ÖRNEK KURUM", "kisiKurum": "Kurum", "rol": "Davacı", "vekil": "[DENEME AVUKAT]"},
        {"adi": "AYNI AD", "kisiKurum": "Kişi", "rol": "Davalı"},
    ]
    captures = [
        {
            "source": "UYAP",
            "path": "/search_phrase_detayli.ajx",
            "data": {"kategori": "Hukuk", "sonuc": [rows, 2]},
        }
    ]
    captures += [
        {
            "source": "UYAP",
            "path": "/dosya_taraf_bilgileri_brd.ajx",
            "data": {"dosyaId": row["dosyaId"], "sonuc": parties},
        }
        for row in rows
    ]
    path = tmp_path / "ornek.json"
    path.write_text(json.dumps(captures), encoding="utf-8")

    initial_clients = Client.objects.count()
    import_files([path], user)
    assert Case.objects.count() == 0
    assert Client.objects.count() == initial_clients
    assert PortalCase.objects.count() == 2
    assert all(record.data["taraf_listeleri"] for record in PortalCase.objects.all())


@pytest.mark.django_db
def test_portal_case_link_requires_admin_and_preserves_office_data(client):
    admin_user = User.objects.create_user(username="portal-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="portal-lawyer", role=User.Role.LAWYER)
    office_client = Client.objects.create(
        kind="company", title="Örnek", responsible_lawyer=lawyer, responsible_intern=lawyer
    )
    case = Case.objects.create(
        client=office_client,
        case_type="civil",
        subject="Örnek",
        responsible_lawyer=lawyer,
        responsible_intern=lawyer,
    )
    record = PortalCase.objects.create(
        fingerprint="ornek-kaynak", authority="Mahkeme", number="2026/1"
    )
    other = PortalCase.objects.create(
        fingerprint="baska-kaynak", authority="Mahkeme", number="2026/2"
    )
    original_client, original_subject = case.client_id, case.subject
    url = f"/portal-inceleme/{record.pk}/bagla/"
    client.force_login(lawyer)
    client.post(url, {"case": case.pk})
    record.refresh_from_db()
    assert record.case_id is None
    client.force_login(admin_user)
    client.post(url, {"case": case.pk})
    record.refresh_from_db()
    case.refresh_from_db()
    assert record.case_id == case.pk
    assert (case.client_id, case.subject) == (original_client, original_subject)
    client.post(f"/portal-inceleme/{other.pk}/bagla/", {"case": case.pk})
    other.refresh_from_db()
    assert other.case_id is None


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_partial_source_update_preserves_previous_list_values(monkeypatch):
    user = User.objects.create_user(username="partial-source-admin", role=User.Role.ADMIN)
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")

    def capture(row):
        return [
            {
                "source": "UYAP",
                "path": "/search_phrase_detayli.ajx",
                "data": {"kategori": "Hukuk", "sonuc": [[row], 1]},
            }
        ]

    base = {"birimAdi": "Örnek Mahkeme", "dosyaNo": "2026/8", "dosyaId": "example"}
    import_captures(
        capture(
            {
                **base,
                "dosyaDurum": "Açık",
                "dosyaAcilisTarihi": {"date": {"day": 1, "month": 2, "year": 2024}},
            }
        ),
        user,
    )
    import_captures(capture({**base, "dosyaDurum": ""}), user)
    record = PortalCase.objects.get()
    assert record.data["liste"]["dosyaDurum"] == "Açık"
    assert record.data["liste"]["dosyaAcilisTarihi"]["date"]["year"] == 2024
