from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.cases.forms import CaseForm
from apps.cases.models import CaseParty, CaseStatus, CaseType
from apps.clients.models import Client
from apps.imports.models import PortalCase
from apps.imports.portal_case_sync import (
    kind_for_uyap,
    missing_related_cases_for_view,
    sync_portal_case,
)
from apps.imports.portal_display import case_information, uyap_subject_value


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin_uyap",
        password="secret",
        role=User.Role.ADMIN,
        first_name="Test",
        last_name="Avukat",
    )


@pytest.fixture
def intern_user(db):
    return User.objects.create_user(
        username="intern_uyap",
        password="secret",
        role=User.Role.INTERN,
        first_name="Stajyer",
        last_name="Bir",
    )


@pytest.fixture
def ministry_client(db, admin_user, intern_user):
    return Client.objects.create(
        kind="company",
        title="AİLE VE SOSYAL HİZMETLER BAKANLIĞI",
        responsible_lawyer=admin_user,
        responsible_intern=intern_user,
        created_by=admin_user,
    )


def test_cbs_category_maps_to_investigation():
    assert kind_for_uyap({}, "CBS") == CaseType.INVESTIGATION
    assert (
        kind_for_uyap({"birimAdi": "Ankara Cumhuriyet Başsavcılığı"}, "") == CaseType.INVESTIGATION
    )


def test_uyap_subject_combines_case_type_and_opening_type(db):
    portal = PortalCase.objects.create(
        fingerprint="d" * 64,
        authority="Mahkeme",
        number="2026/1",
        data={
            "ayrintilar": [
                {
                    "davaTurleriStr": "Alacak",
                    "davaAcilisTuruStr": "Normal Dava",
                }
            ]
        },
    )
    assert uyap_subject_value(portal) == "Alacak · Normal Dava"


def test_sync_enforcement_case_separates_basis_and_populates_account_tab(
    db, admin_user, ministry_client
):
    portal = PortalCase.objects.create(
        fingerprint="f" * 64,
        authority="Gaziosmanpaşa İcra Dairesi",
        number="2026/33950",
        category="İcra",
        status="Kapalı (İnfaz)(30/06/2026)",
        data={
            "liste": {
                "birimAdi": "Gaziosmanpaşa İcra Dairesi",
                "dosyaNo": "2026/33950",
                "dosyaDurum": "Kapalı (İnfaz)(30/06/2026)",
                "dosyaAcilisTarihi": {"date": {"year": 2026, "month": 6, "day": 10}},
            },
            "ayrintilar": [
                {
                    "takibinTuruAciklama": "İLAMLI",
                    "takibinYoluAciklama": "Genel Haciz Yolu",
                    "takibinSekliAciklama": "Para Alacağı",
                    "alacakKalemToplamTutar": "35.000,00 TL",
                    "vekaletUcreti": "3.268,00 TL",
                }
            ],
            "hesaplar": [
                [
                    {"textAlan": "Takipte Kesinleşen Miktar", "degerAlan": "35000.00"},
                    {"textAlan": "Toplam Alacak", "degerAlan": "38268.00"},
                ]
            ],
            "taraf_listeleri": [
                [
                    {
                        "adi": "AİLE VE SOSYAL HİZMETLER BAKANLIĞI",
                        "rol": "Alacaklı",
                        "kisiKurum": "Kurum",
                        "vekil": "[TEST AVUKAT]",
                    },
                    {
                        "adi": "TEST TARAF",
                        "rol": "Borçlu",
                        "kisiKurum": "Kişi",
                        "vekil": "[]",
                    },
                ]
            ],
        },
    )
    case = sync_portal_case(portal, default_user=admin_user, create_missing=True)
    assert case is not None
    assert case.case_type == CaseType.ENFORCEMENT
    assert case.status == CaseStatus.CLOSED
    assert case.closed_on == date(2026, 6, 30)
    assert case.closing_reason == "fully_collected"
    assert case.uyap_status_banner == "KAPALI: 30.06.2026 · İnfaz"
    assert case.enforcement_type == "ilamli"
    assert case.enforcement_amount == Decimal("35000.00")
    assert case.enforcement_basis == ""
    assert case.client == ministry_client
    assert case.client_role == "creditor"
    assert "Fiziki arşiv no" in case.missing_fields
    assert "Konu" in case.missing_fields

    party_links = list(CaseParty.objects.filter(case=case).select_related("party"))
    assert len(party_links) == 1
    assert party_links[0].party.name == "TEST TARAF"
    assert party_links[0].role == "debtor"
    assert party_links[0].from_uyap is True

    info = case_information(portal)
    field_dict = dict(info["fields"])
    assert field_dict["Takibin yolu"] == "Genel Haciz Yolu"
    assert field_dict["Takibin şekli"] == "Para Alacağı"
    account_dict = dict(info["account"])
    assert "Takipte Kesinleşen Miktar" in account_dict
    assert "Vekâlet ücreti" in account_dict


def test_open_administrative_case_keeps_first_instance_decision_and_next_hearing(
    db, admin_user, ministry_client
):
    portal = PortalCase.objects.create(
        fingerprint="a" * 64,
        authority="İstanbul 5. İdare Mahkemesi",
        number="2025/1200",
        category="İdari Yargı",
        status="Açık",
        data={
            "liste": {
                "birimAdi": "İstanbul 5. İdare Mahkemesi",
                "dosyaNo": "2025/1200",
                "dosyaDurum": "Açık",
                "dosyaAcilisTarihi": {"date": {"year": 2025, "month": 4, "day": 12}},
            },
            "ayrintilar": [
                {
                    "dosyaDurumu": "Bölge İdare Mahkemesinde",
                    "davaninKonusu": "İptal Davası",
                    "davaAcilisTuruStr": "Normal Dava",
                    "kararNo": "2025/980",
                    "kararTarihi": "15/11/2025",
                    "karar": "Davanın Reddi",
                    "durusmaTarihiStr": "20.12.2026 10:30",
                    "ilgiliDosyaListesiStr": "İstanbul Bölge İdare Mahkemesi 1. İdari Dava Dairesi - 2026/45",
                }
            ],
            "taraf_listeleri": [
                [
                    {
                        "adi": "AİLE VE SOSYAL HİZMETLER BAKANLIĞI",
                        "rol": "Davalı",
                        "kisiKurum": "Kurum",
                        "vekil": "[TEST AVUKAT]",
                    }
                ]
            ],
        },
    )
    case = sync_portal_case(portal, default_user=admin_user, create_missing=True)
    assert case.is_open is True
    assert case.stage == "appeal"
    assert case.uyap_stage == "Bölge İdare Mahkemesinde"
    assert case.uyap_status_banner == "AÇIK: Bölge İdare Mahkemesinde"
    assert case.uyap_subject == "İptal Davası · Normal Dava"
    assert case.decision_no == "2025/980"
    assert case.decision_date == date(2025, 11, 15)
    assert case.next_hearing_at is not None

    info = case_information(portal)
    fields = dict(info["fields"])
    assert fields["Karar numarası"] == "2025/980"
    assert fields["Karar tarihi"] == "15.11.2025"
    assert fields["Karar sonucu"] == "Davanın Reddi"

    missing_rel = missing_related_cases_for_view(case)
    assert len(missing_rel) == 1
    assert missing_rel[0]["authority"] == "İstanbul Bölge İdare Mahkemesi 1. İdari Dava Dairesi"
    assert missing_rel[0]["number"] == "2026/45"


def test_uyap_linked_case_form_disables_uyap_fields_and_requires_office_fields(
    db, admin_user, intern_user, ministry_client
):
    portal = PortalCase.objects.create(
        fingerprint="b" * 64,
        authority="Ankara 2. Asliye Hukuk Mahkemesi",
        number="2026/100",
        category="Hukuk",
        status="Açık",
        data={
            "liste": {
                "birimAdi": "Ankara 2. Asliye Hukuk Mahkemesi",
                "dosyaNo": "2026/100",
                "dosyaDurum": "Açık",
                "dosyaAcilisTarihi": {"date": {"year": 2026, "month": 1, "day": 15}},
            },
            "ayrintilar": [{"dosyaDurumu": "Ön İncelemede"}],
            "taraf_listeleri": [
                [
                    {
                        "adi": "MEHMET KAYA",
                        "rol": "Davalı",
                        "kisiKurum": "Kişi",
                    }
                ]
            ],
        },
    )
    case = sync_portal_case(portal, default_user=admin_user, create_missing=True)
    case.refresh_from_db()
    form = CaseForm(instance=case, can_remove_parties=True)
    for field_name in (
        "case_type",
        "opened_on",
        "authority",
        "official_year",
        "official_sequence",
        "official_no_kind",
    ):
        assert form.fields[field_name].disabled is True
    for link, role_field in form.existing_party_rows:
        assert link.from_uyap is True
        assert role_field.field.disabled is True
        assert getattr(link, "remove_field", None) is None


def test_case_detail_renders_split_info_and_enforcement_account_tab(
    client, admin_user, ministry_client
):
    portal = PortalCase.objects.create(
        fingerprint="c" * 64,
        authority="Gaziosmanpaşa İcra Dairesi",
        number="2026/33950",
        category="İcra",
        status="Açık",
        data={
            "liste": {
                "birimAdi": "Gaziosmanpaşa İcra Dairesi",
                "dosyaNo": "2026/33950",
                "dosyaDurum": "Açık",
                "dosyaAcilisTarihi": {"date": {"year": 2026, "month": 6, "day": 10}},
            },
            "ayrintilar": [
                {
                    "takibinTuruAciklama": "İLAMLI",
                    "takibinYoluAciklama": "Genel Haciz Yolu",
                    "takibinSekliAciklama": "Para Alacağı",
                }
            ],
            "hesaplar": [
                [
                    {"textAlan": "Takipte Kesinleşen Miktar", "degerAlan": "35000.00"},
                    {"textAlan": "Tahsil Harcı", "degerAlan": "1218.03"},
                ]
            ],
        },
    )
    case = sync_portal_case(portal, default_user=admin_user, create_missing=True)
    client.force_login(admin_user)
    response = client.get(reverse("cases:detail", args=[case.pk]))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Dosya bilgileri (Büro)" in html
    assert "UYAP bilgileri" in html
    assert "Dosya Hesabı" in html
    assert "Genel Haciz Yolu" in html
    assert "Eksik büro bilgisi:" in html
