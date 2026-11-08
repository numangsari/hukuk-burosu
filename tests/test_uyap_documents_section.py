import base64
import datetime as dt
import importlib
import json

import pytest
from django.apps import apps as django_apps
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.cases.models import Document, DocumentSource
from apps.imports.models import PortalCase, PortalDocument, PortalLawyerAccess

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\nornek evrak"
INGEST = "/portal-inceleme/eklentiden-al/"


@pytest.fixture
def admin_client_view():
    admin = User.objects.create_user(username="uyap-bolum-yonetici", role=User.Role.ADMIN)
    client = Client()
    client.force_login(admin)
    return client, admin


def make_document(case, title, source=DocumentSource.UYAP, **values):
    document = Document(
        case=case, title=title, original_name=f"{title}.pdf", source=source, **values
    )
    document.file.save(f"{title}.pdf", ContentFile(PDF), save=False)
    document.save()
    return document


def uyap_url(case, **params):
    from urllib.parse import urlencode

    base = reverse("cases:uyap_documents", args=[case.pk])
    return base + ("?" + urlencode(params) if params else "")


# ---- içe aktarma: kaynak, ad ve başlık -------------------------------------------------


@pytest.fixture
def ingest_setup(case_factory, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    lawyer = User.objects.create_user(username="bolum-avukat", role=User.Role.LAWYER)
    PortalLawyerAccess.objects.create(
        user=lawyer, identity_number="10000000146", uyap_enabled=True, uets_enabled=True
    )
    admin = User.objects.create_user(username="bolum-esleyen", role=User.Role.ADMIN)
    owner = Client()
    owner.force_login(admin)
    key = owner.post("/portal-inceleme/baglanti/").context["pair_key"]
    case = case_factory()
    portal = PortalCase.objects.create(
        fingerprint="bolum-dosya",
        authority="Örnek Mahkeme",
        number="2026/7",
        data={"liste": {"dosyaId": "D7"}},
        case=case,
        source_unknown=False,
    )
    portal.source_users.add(lawyer)
    return Client(), {"HTTP_AUTHORIZATION": f"Bearer {key}"}, case, portal


def send(ingest_setup, **values):
    client, auth, *_ = ingest_setup
    payload = {
        "type": "uyap_document",
        "identity": "10000000146",
        "dosyaId": "D7",
        "evrakId": "E1",
        "meta": {"tur": "Kapalı Tebligat", "onaylandigiTarih": "14/10/2026"},
        "name": "evrak_14885929256.pdf",
        "content": base64.b64encode(PDF).decode(),
    }
    payload.update(values)
    return client.post(INGEST, json.dumps(payload), content_type="application/json", **auth)


def test_ingested_evrak_is_marked_uyap_with_readable_title_and_file_name(ingest_setup):
    assert send(ingest_setup).status_code == 200
    document = Document.objects.get()
    assert document.source == DocumentSource.UYAP
    assert document.uyap_type == "Kapalı Tebligat"
    assert document.title == "Kapalı Tebligat · 14/10/2026"
    assert document.original_name == "14-10-2026 Kapalı Tebligat.pdf"
    assert document.document_date == dt.date(2026, 10, 14)


def test_evrak_without_date_or_type_gets_plain_names(ingest_setup):
    send(ingest_setup, meta={}, evrakId="E2")
    document = Document.objects.get()
    assert document.title == "UYAP evrakı"
    assert document.original_name == "UYAP evrakı.pdf"
    assert document.uyap_type == ""


def test_unsafe_characters_in_type_are_removed_from_file_name(ingest_setup):
    send(
        ingest_setup,
        meta={"tur": 'Dilekçe: "A/B"?', "onaylandigiTarih": "01.02.2026"},
        evrakId="E3",
    )
    name = Document.objects.get().original_name
    assert name.startswith("01-02-2026 ")
    assert not any(ch in name for ch in '<>:"/\\|?*')


def test_office_documents_default_to_office_source(case_factory):
    document = make_document(case_factory(), "Elle", source=DocumentSource.OFFICE)
    assert document.source == DocumentSource.OFFICE
    assert Document.objects.office().count() == 1
    assert Document.objects.uyap().count() == 0


# ---- salt okunur -------------------------------------------------------------------------


def test_uyap_document_cannot_be_deleted_even_by_admin(case_factory, admin_client_view):
    client, admin = admin_client_view
    case = case_factory()
    document = make_document(case, "UYAP belgesi", created_by=admin)
    response = client.post(reverse("cases:document_delete", args=[case.pk, document.pk]))
    assert response.status_code == 403
    assert Document.objects.filter(pk=document.pk).exists()


def test_office_document_can_still_be_deleted_by_uploader(case_factory, admin_client_view):
    client, admin = admin_client_view
    case = case_factory()
    document = make_document(case, "Büro belgesi", source=DocumentSource.OFFICE, created_by=admin)
    response = client.post(reverse("cases:document_delete", args=[case.pk, document.pk]))
    assert response.status_code == 200
    assert not Document.objects.filter(pk=document.pk).exists()


# ---- Belgeler sekmesi: iki ayrı bölüm ------------------------------------------------------


def test_documents_tab_keeps_office_and_uyap_documents_apart(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Büro dilekçesi", source=DocumentSource.OFFICE)
    make_document(case, "UYAP tebligatı")
    html = client.get(case.get_absolute_url()).content.decode()
    office_part, uyap_part = html.split('id="uyap-documents"', 1)
    assert "Büro dilekçesi" in office_part and "UYAP tebligatı" not in office_part
    assert "UYAP tebligatı" in uyap_part and "Büro dilekçesi" not in uyap_part


def test_uyap_section_has_no_delete_or_upload_controls(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "UYAP tebligatı")
    html = client.get(uyap_url(case)).content.decode()
    assert "UYAP tebligatı" in html
    assert (
        "document_delete" not in html
        and reverse("cases:document_delete", args=[case.pk, 1]) not in html
    )
    assert 'type="file"' not in html
    assert "Salt okunur" in html


def test_uyap_section_shows_count_and_last_received_date(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    for index in range(3):
        make_document(case, f"Evrak {index}")
    html = client.get(uyap_url(case)).content.decode()
    assert "3 evrak" in html


def test_uyap_section_empty_state(case_factory, admin_client_view):
    client, _ = admin_client_view
    html = client.get(uyap_url(case_factory())).content.decode()
    assert "UYAP evrakı yok" in html


# ---- filtre, sıralama, sayfalama -----------------------------------------------------------


def titles(response):
    return [d.title for d in response.context["page"].object_list]


def test_filter_by_exact_uyap_name(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Kapalı Tebligat · 01.01.2026", uyap_type="Kapalı Tebligat")
    make_document(case, "Genel Müzekkere · 02.01.2026", uyap_type="Genel Müzekkere")
    make_document(
        case, "Kapalı E-Tebliğ Mazbatası · 03.01.2026", uyap_type="Kapalı E-Tebliğ Mazbatası"
    )
    response = client.get(uyap_url(case, tur="Kapalı Tebligat"))
    assert titles(response) == ["Kapalı Tebligat · 01.01.2026"]


def test_name_choices_list_the_uyap_names_of_this_case_only(case_factory, admin_client_view):
    client, _ = admin_client_view
    case, other = case_factory(), case_factory()
    make_document(case, "A", uyap_type="Genel Müzekkere")
    make_document(case, "B", uyap_type="Genel Müzekkere")
    make_document(case, "C", uyap_type="Kapalı Tebligat")
    make_document(other, "D", uyap_type="Başka Dosyanın Evrakı")
    response = client.get(uyap_url(case))
    assert [(n["name"], n["count"]) for n in response.context["uyap_names"]] == [
        ("Genel Müzekkere", 2),
        ("Kapalı Tebligat", 1),
    ]


def test_unknown_uyap_name_filter_shows_nothing(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "A", uyap_type="Genel Müzekkere")
    assert titles(client.get(uyap_url(case, tur="Yok"))) == []


def test_sort_by_name_and_date_in_both_directions(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Z-evrak", uyap_type="Zeyilname", document_date=dt.date(2026, 1, 1))
    make_document(case, "A-evrak", uyap_type="Ara Karar", document_date=dt.date(2026, 3, 1))
    make_document(case, "M-evrak", uyap_type="Müzekkere", document_date=dt.date(2026, 2, 1))
    assert titles(client.get(uyap_url(case))) == [
        "A-evrak",
        "M-evrak",
        "Z-evrak",
    ]  # varsayılan: yeni tarih önce
    assert titles(client.get(uyap_url(case, sirala="tarih"))) == ["Z-evrak", "M-evrak", "A-evrak"]
    assert titles(client.get(uyap_url(case, sirala="ad"))) == ["A-evrak", "M-evrak", "Z-evrak"]
    assert titles(client.get(uyap_url(case, sirala="-ad"))) == ["Z-evrak", "M-evrak", "A-evrak"]


def test_invalid_sort_falls_back_to_newest_first(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Eski", document_date=dt.date(2025, 1, 1))
    make_document(case, "Yeni", document_date=dt.date(2026, 1, 1))
    assert titles(client.get(uyap_url(case, sirala="rastgele"))) == ["Yeni", "Eski"]


def test_uyap_section_has_no_category_column_or_filter(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Evrak", uyap_type="Genel Müzekkere")
    html = client.get(uyap_url(case)).content.decode()
    assert "Kategori" not in html
    assert 'name="tur"' in html


def test_filter_by_search_text_in_title_and_type(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Tensip Zaptı · 05.11.2026", uyap_type="Tensip Zaptı")
    make_document(case, "Reddiyat Makbuzu · 06.11.2026", uyap_type="Reddiyat Makbuzu")
    assert titles(client.get(uyap_url(case, q="tensip"))) == ["Tensip Zaptı · 05.11.2026"]
    assert titles(client.get(uyap_url(case, q="makbuz"))) == ["Reddiyat Makbuzu · 06.11.2026"]


def test_filter_by_date_range_uses_uyap_date(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Eski", document_date=dt.date(2025, 1, 5))
    make_document(case, "Orta", document_date=dt.date(2026, 3, 10))
    make_document(case, "Yeni", document_date=dt.date(2026, 10, 20))
    assert titles(client.get(uyap_url(case, bas="2026-01-01", bit="2026-06-30"))) == ["Orta"]
    assert titles(client.get(uyap_url(case, bas="2026-04-01"))) == ["Yeni"]
    assert titles(client.get(uyap_url(case, bit="2025-12-31"))) == ["Eski"]


def test_default_order_is_newest_uyap_date_first(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Orta", document_date=dt.date(2026, 3, 10))
    make_document(case, "Eski", document_date=dt.date(2025, 1, 5))
    make_document(case, "Yeni", document_date=dt.date(2026, 10, 20))
    assert titles(client.get(uyap_url(case))) == ["Yeni", "Orta", "Eski"]


def test_invalid_date_filter_is_ignored(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Evrak", document_date=dt.date(2026, 3, 10))
    assert titles(client.get(uyap_url(case, bas="dün", bit="yarın"))) == ["Evrak"]


def test_pagination_splits_into_pages_of_fifty(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    for index in range(55):
        make_document(
            case, f"Evrak {index:02d}", document_date=dt.date(2026, 1, 1) + dt.timedelta(days=index)
        )
    first = client.get(uyap_url(case))
    assert len(first.context["page"].object_list) == 50
    assert first.context["page"].paginator.num_pages == 2
    second = client.get(uyap_url(case, sayfa=2))
    assert len(second.context["page"].object_list) == 5


def test_page_beyond_range_shows_last_page(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Evrak")
    assert titles(client.get(uyap_url(case, sayfa=99))) == ["Evrak"]


def test_filter_view_never_lists_office_documents(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Büro belgesi", source=DocumentSource.OFFICE)
    make_document(case, "UYAP belgesi")
    assert titles(client.get(uyap_url(case))) == ["UYAP belgesi"]


def test_filter_view_requires_login_and_case_visibility(case_factory, lawyer, settings):
    case = case_factory()
    anonymous = Client().get(uyap_url(case))
    assert anonymous.status_code == 302
    from apps.office.models import OfficeSettings

    office = OfficeSettings.load()
    office.role_permissions = {"cases.view_all": ["admin", "senior", "secretary", "accountant"]}
    office.save()
    outsider = User.objects.create_user(username="dosya-disi", role=User.Role.LAWYER)
    client = Client()
    client.force_login(outsider)
    assert client.get(uyap_url(case)).status_code == 404
    assert lawyer is not None


# ---- geri doldurma (eski kayıtlar) ----------------------------------------------------------


def test_backfill_marks_old_uyap_documents_and_renames_them(case_factory):
    migration = importlib.import_module("apps.cases.migrations.0050_document_source")
    case = case_factory()
    old = Document(
        case=case,
        title="Kapalı Tebligat (14/10/2026)",
        original_name="evrak_123.pdf",
        notes="UYAP evrakı · Birim evrak no: 11",
        document_date=dt.date(2026, 10, 14),
    )
    old.file.save("evrak_123.pdf", ContentFile(PDF), save=False)
    old.save()
    manual = Document(case=case, title="Elle (14/10/2026)", original_name="x.pdf", notes="not")
    manual.file.save("x.pdf", ContentFile(PDF), save=False)
    manual.save()

    migration.backfill_document_source(django_apps, None)

    old.refresh_from_db()
    manual.refresh_from_db()
    assert old.source == DocumentSource.UYAP
    assert old.uyap_type == "Kapalı Tebligat"
    assert old.title == "Kapalı Tebligat · 14.10.2026"
    assert old.original_name == "2026-10-14 Kapalı Tebligat.pdf"
    assert manual.source == DocumentSource.OFFICE
    assert manual.title == "Elle (14/10/2026)"
    assert PortalDocument.objects.count() == 0


def test_uyap_section_shows_dates_in_slash_format(case_factory, admin_client_view):
    client, _ = admin_client_view
    case = case_factory()
    make_document(case, "Evrak · 19/10/2026", document_date=dt.date(2026, 10, 19))
    html = client.get(uyap_url(case)).content.decode()
    assert "19/10/2026" in html
    assert "19.10.2026" not in html


def test_reformat_migration_rewrites_uyap_names_to_slash_dates(case_factory):
    migration = importlib.import_module("apps.cases.migrations.0051_uyap_document_name_format")
    case = case_factory()
    document = make_document(
        case,
        "Kapalı Tebligat · 14.10.2026",
        uyap_type="Kapalı Tebligat",
        document_date=dt.date(2026, 10, 14),
    )
    document.original_name = "2026-10-14 Kapalı Tebligat.pdf"
    document.save()
    manual = make_document(
        case, "Elle · 14.10.2026", source=DocumentSource.OFFICE, document_date=dt.date(2026, 10, 14)
    )

    migration.reformat_uyap_document_names(django_apps, None)

    document.refresh_from_db()
    manual.refresh_from_db()
    assert document.title == "Kapalı Tebligat · 14/10/2026"
    assert document.original_name == "14-10-2026 Kapalı Tebligat.pdf"
    assert manual.title == "Elle · 14.10.2026"
