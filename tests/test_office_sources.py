from datetime import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from openpyxl import Workbook

from apps.accounts.models import User
from apps.cases.forms import CaseForm
from apps.cases.models import Case
from apps.clients.models import Client
from apps.imports.models import OfficeSourceRecord
from apps.imports.office_sources import amount, execute

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _archived_imports_urls(settings):
    """Veri aktarımı adresleri uygulamaya bağlı değildir; kodu yalnızca bu denemelerde açılır."""
    settings.ROOT_URLCONF = "tests.urls_archived_imports"


@pytest.fixture
def office_files(tmp_path, settings):
    settings.POA_REVIEW_TEAMS = (("test_avukat", "test_stajyer"),)
    lawyer = User.objects.create_user(username="test_avukat", role="lawyer")
    intern = User.objects.create_user(username="test_stajyer", role="intern")
    client = Client.objects.create(
        kind="person",
        first_name="AYŞE",
        last_name="ÖRNEK",
        responsible_lawyer=lawyer,
        responsible_intern=intern,
    )
    archive = Workbook()
    archive.active.title = "AÇIK"
    archive.active.append(
        ["KLASÖR NO", "DOSYA NO", "MAHKEME", "DOSYA/ESAS NO", "DAVACI", "DAVALI", "NOT"]
    )
    archive.active.append(
        [1, 2, "ÖRNEK HUKUK MAHKEMESİ", "2024/1", "AYŞE ÖRNEK", "DİĞER KİŞİ", "Örnek not"]
    )
    archive.active.append(
        [1, 3, "ÖRNEK HUKUK MAHKEMESİ", "2024/2", "TANINMAYAN KİŞİ", "DİĞER KİŞİ"]
    )
    archive.create_sheet("KAPALI").append(
        ["KLASÖR NO", "DOSYA NO", "MAHKEME", "DOSYA/ESAS NO", "DAVACI", "DAVALI", "NOT"]
    )
    archive.create_sheet("KAPALI1")
    archive_path = tmp_path / "arsiv.xlsx"
    archive.save(archive_path)
    settings.OFFICE_ARCHIVE_FILE = archive_path
    enforcement = Workbook()
    enforcement.active.title = "TAKİP"
    enforcement.active.append(
        [
            "AÇILIŞ",
            "SKT",
            "BİRİM",
            "DOSYA NO",
            "ALACAKLI",
            "BORÇLU",
            "MÜVEKKİL",
            "NOT",
            "DURUM",
            "ARAÇ",
            "TAŞINMAZ",
            "MAAŞ",
            "BANKA",
            "DOSYA",
            "TAŞINIR",
            "89",
            "HACİZ NOTU",
            "TAHSİLAT NOTU",
            "ESAS ALACAK",
            "FAİZ",
            "MASRAF",
        ]
    )
    enforcement.active.append(
        [
            datetime(2024, 2, 1),
            None,
            "ÖRNEK İCRA",
            "2024/7",
            "AYŞE ÖRNEK",
            "DİĞER KİŞİ",
            "AYŞE ÖRNEK",
            None,
            None,
            True,
            None,
            None,
            None,
            None,
            None,
            None,
            "Örnek bilgi",
            None,
            1234.5,
            800,
            500,
        ]
    )
    enforcement_path = tmp_path / "icra.xlsx"
    enforcement.save(enforcement_path)
    settings.OFFICE_ENFORCEMENT_FILE = enforcement_path
    return client


def test_import_saves_only_certain_rows_without_inventing_transactions(office_files):
    counts = execute()
    assert counts["created"] == 2
    assert counts["pending"] == 1
    case = Case.objects.get(case_type="enforcement")
    assert case.client == office_files
    assert case.enforcement_amount == Decimal("1234.50")
    assert case.opened_on.isoformat() == "2024-02-01"
    assert case.archive_no == ""
    assert case.stage == ""
    assert not case.ledger_entries.exists()
    assert not case.seizures.exists()
    source = case.office_sources.get()
    assert "FAİZ" not in source.values
    assert "MASRAF" not in source.values
    case.notes = "Sonradan eklenen not"
    case.save()
    assert case.stage == ""
    assert execute()["previous"] == 2
    assert Case.objects.count() == 2
    assert OfficeSourceRecord.objects.filter(case__isnull=True).count() == 1


def test_incomplete_import_can_be_edited_without_fabricated_values(office_files):
    execute()
    case = Case.objects.get(case_type="enforcement")
    form = CaseForm(
        data={
            "client": case.client_id,
            "case_type": case.case_type,
            "client_role": case.client_role,
            "authority": case.authority,
            "official_year": "2024",
            "official_sequence": "7",
            "enforcement_amount": "1234.50",
            "opened_on": "2024-02-01",
            "responsible_lawyer": case.responsible_lawyer_id,
            "responsible_intern": case.responsible_intern_id,
        },
        instance=case,
    )
    assert form.is_valid(), form.errors


def test_review_page_requires_admin_and_shows_reason(office_files, client, admin_user):
    execute()
    client.force_login(admin_user)
    response = client.get(reverse("imports:office_review"))
    assert response.status_code == 200
    assert "TANINMAYAN KİŞİ" in response.content.decode()
    assert "FAİZ" not in response.content.decode()


def test_user_can_link_a_review_row_without_changing_the_case(office_files, client, admin_user):
    execute()
    row = OfficeSourceRecord.objects.get(case__isnull=True)
    case = Case.objects.get(case_type="enforcement")
    client.force_login(admin_user)
    url = reverse("imports:office_review_detail", args=[row.pk])
    assert client.get(url).status_code == 200
    response = client.post(url, {"case": case.pk})
    assert response.status_code == 302
    row.refresh_from_db()
    case.refresh_from_db()
    assert row.case == case
    assert not row.reason
    assert case.enforcement_amount == Decimal("1234.50")
    assert not case.ledger_entries.exists()


@pytest.mark.parametrize("value", ["3.000", "abc", -1, "NaN"])
def test_ambiguous_amount_is_not_guessed(value):
    with pytest.raises(ValueError):
        amount(value)


def test_new_case_can_be_created_from_a_review_row(office_files, client, admin_user):
    from apps.cases.models import ArchiveFolder

    execute()
    ArchiveFolder.objects.filter(name="Açık 1").update(capacity=8)
    row = OfficeSourceRecord.objects.get(case__isnull=True)
    client.force_login(admin_user)
    url = reverse("cases:create") + f"?kaynak={row.pk}"
    page = client.get(url)
    assert page.status_code == 200
    html = page.content.decode()
    assert f'name="source_record" value="{row.pk}"' in html
    assert "ÖRNEK HUKUK MAHKEMESİ" in html
    assert 'value="2024"' in html and 'value="2"' in html
    response = client.post(
        reverse("cases:create"),
        {
            "source_record": row.pk,
            "client": office_files.pk,
            "case_type": "civil",
            "client_role": "plaintiff",
            "archive_folder_no": "Açık 1",
            "archive_no": "3",
            "official_year": "2024",
            "official_sequence": "2",
            "authority": "ÖRNEK HUKUK MAHKEMESİ",
            "subject": "ALACAK",
            "opened_on": "2024-03-01",
            "parties-TOTAL_FORMS": "0",
            "parties-INITIAL_FORMS": "0",
            "coclients-TOTAL_FORMS": "0",
            "coclients-INITIAL_FORMS": "0",
        },
    )
    assert response.status_code == 302, response.content.decode()[:500]
    row.refresh_from_db()
    assert row.case and row.case.subject == "ALACAK" and not row.reason
    assert not OfficeSourceRecord.objects.filter(case__isnull=True).exists()


def test_import_leaves_out_of_capacity_location_for_review(office_files):
    from apps.cases.models import ArchiveFolder

    ArchiveFolder.objects.create(name="Açık 1", kind="open", capacity=1)
    execute()
    assert not Case.objects.filter(archive_folder_no="Açık 1", archive_no="2").exists()
    assert OfficeSourceRecord.objects.filter(reason__icontains="1 ile 1").exists()


def test_source_prefill_is_ignored_for_non_admin(office_files, client):
    execute()
    row = OfficeSourceRecord.objects.get(case__isnull=True)
    user = User.objects.create_user(username="test_stajyer2", role="intern")
    client.force_login(user)
    response = client.get(reverse("cases:create") + f"?kaynak={row.pk}")
    assert 'name="source_record"' not in response.content.decode()


def test_bulk_list_creates_case_from_client_and_type(office_files, client, admin_user):
    execute()
    row = OfficeSourceRecord.objects.get(case__isnull=True)
    client.force_login(admin_user)
    page = client.get(reverse("imports:office_bulk"))
    assert page.status_code == 200
    assert "TANINMAYAN KİŞİ" in page.content.decode()
    response = client.post(
        reverse("imports:office_bulk"),
        {
            "rid": [row.pk],
            f"client_{row.pk}": f"{office_files.name} [#{office_files.pk}]",
            f"type_{row.pk}": "civil",
        },
    )
    assert response.status_code == 302
    row.refresh_from_db()
    assert row.case and row.case.client == office_files and row.case.case_type == "civil"
    assert row.case.archive_folder_no == "Açık 1" and row.case.archive_no == "3"
    assert not row.reason


def test_bulk_list_skip_is_remembered_and_import_ignores_it(office_files, client, admin_user):
    execute()
    row = OfficeSourceRecord.objects.get(case__isnull=True)
    client.force_login(admin_user)
    client.post(reverse("imports:office_bulk"), {"rid": [row.pk], f"skip_{row.pk}": "on"})
    row.refresh_from_db()
    assert row.skipped and not row.case_id
    assert execute()["skipped"] == 1
    listing = client.get(reverse("imports:office_review"))
    assert "TANINMAYAN KİŞİ" not in listing.content.decode()
    skipped = client.get(reverse("imports:office_bulk") + "?durum=skipped")
    assert "TANINMAYAN KİŞİ" in skipped.content.decode()
    client.post(reverse("imports:office_bulk"), {"rid": [row.pk], f"unskip_{row.pk}": "on"})
    row.refresh_from_db()
    assert not row.skipped


def test_bulk_list_requires_admin(office_files, client):
    user = User.objects.create_user(username="test_stajyer3", role="intern")
    client.force_login(user)
    assert client.get(reverse("imports:office_bulk")).status_code in (302, 403)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026/151", "2026/151"),
        ("2026/151 E", "2026/151"),
        ("2026/151 E.", "2026/151"),
        ("2026/151 Esas", "2026/151"),
        ("2025/ 46 E", "2025/46"),
        ("2018/7977 D. İŞ", "2018/7977 D. İŞ"),
        ("YEVMİYE NO: 22060", "YEVMİYE NO: 22060"),
    ],
)
def test_normalize_number(raw, expected):
    from apps.imports.office_sources import normalize_number

    assert normalize_number(raw) == expected
