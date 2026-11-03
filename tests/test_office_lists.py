import json

import pytest
from openpyxl import load_workbook

from apps.core import office_lists
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def office_directory(tmp_path, monkeypatch):
    office = OfficeSettings.load()
    office.documents_root = str(tmp_path)
    office.calendar_ics_url = ""
    office.save()
    return tmp_path / office_lists.DIRECTORY


def worksheet(path):
    return load_workbook(path, data_only=False).active


def test_all_lists_created_from_synthetic_data_and_safe_strings(office_directory, client_factory):
    client = client_factory(first_name="=ORNEK", last_name="KİŞİ")
    result = office_lists.update_office_lists()
    assert not result["issues"]
    assert len(list(office_directory.glob("*.xlsx"))) == len(office_lists.SPECS) + 2
    sheet = worksheet(office_directory / "Müvekkiller.xlsx")
    headers = [cell.value for cell in sheet[5]]
    name_column = headers.index("Ad / unvan") + 1
    value = sheet.cell(6, name_column)
    assert value.value == client.name
    assert value.data_type == "s"
    user_headers = [cell.value for cell in worksheet(office_directory / "Kullanıcılar.xlsx")[5]]
    assert "Password" not in user_headers
    assert "Parola" not in user_headers
    assert "Takvim" in worksheet(office_directory / "Takvim.xlsx").title


def test_updated_data_refreshes_without_overwriting_user_changes(office_directory, client_factory):
    client = client_factory(first_name="Örnek", last_name="Kişi")
    office_lists.update_office_lists()
    client_file = office_directory / "Müvekkiller.xlsx"
    untouched_file = office_directory / "Görev Türleri.xlsx"
    original = client_file.read_bytes()
    untouched = untouched_file.read_bytes()
    client.first_name = "Başka"
    client.save()
    result = office_lists.update_office_lists()
    assert not result["issues"]
    assert client_file.read_bytes() != original
    assert untouched_file.read_bytes() == untouched
    client_file.write_bytes(b"kullanici-degisikligi")
    client.first_name = "Yeni"
    client.save()
    result = office_lists.update_office_lists()
    assert client_file.read_bytes() == b"kullanici-degisikligi"
    assert any(issue["file"] == "Müvekkiller.xlsx" for issue in result["issues"])
    assert office_lists.office_lists_status()["issues"]


def test_unowned_existing_file_is_never_overwritten(office_directory):
    office_directory.mkdir()
    existing = office_directory / "Müvekkiller.xlsx"
    existing.write_bytes(b"baska-kisi-dosyasi")
    result = office_lists.update_office_lists()
    assert existing.read_bytes() == b"baska-kisi-dosyasi"
    assert any(issue["file"] == existing.name for issue in result["issues"])
    state = json.loads((office_directory / office_lists.STATE_FILE).read_text(encoding="utf-8"))
    assert existing.name not in state["files"]


def test_populated_sections_refresh_with_synthetic_records(
    office_directory, client_factory, case_factory, lawyer, intern, settings, tmp_path
):
    import datetime as dt
    from decimal import Decimal

    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    from apps.accounting.models import LedgerEntry
    from apps.cases.models import (
        CaseCoClient,
        CaseEvent,
        CaseParty,
        Document,
        Seizure,
        SeizureRenewal,
    )
    from apps.clients.models import (
        ClientContact,
        ClientIban,
        ClientRepresentative,
        Party,
        PowerOfAttorney,
        RetainerAgreement,
    )
    from apps.imports.models import PortalCase, PortalNotice, PortalNoticeDocument
    from apps.office.models import TaskType
    from apps.tasks.models import Task, TaskDocument, TaskEvent, TaskPoint

    settings.MEDIA_ROOT = tmp_path / "media"
    client = client_factory(first_name="Örnek", last_name="Kişi")
    other = client_factory(first_name="Başka", last_name="Kişi")
    case = case_factory(client=client, subject="Örnek dosya")
    party = Party.objects.create(kind="person", name="DENEME KİŞİ")
    CaseCoClient.objects.create(case=case, client=other, role="plaintiff")
    CaseParty.objects.create(case=case, party=party, role="defendant")
    ClientContact.objects.create(client=client, kind="address", value="Örnek adres")
    ClientIban.objects.create(client=client, iban="TR000000000000000000000000")
    ClientRepresentative.objects.create(client=client, name="Örnek yetkili")
    PowerOfAttorney.objects.create(
        client=client, notary="Örnek noter", date=dt.date(2026, 1, 1), journal_no="1"
    )
    RetainerAgreement.objects.create(
        client=client, case=case, signed_on=dt.date(2026, 1, 1), fee_amount=Decimal("120.00")
    )
    CaseEvent.objects.create(case=case, date=dt.date(2026, 1, 1), title="Örnek not")
    Document.objects.create(
        case=case, title="Örnek belge", file=SimpleUploadedFile("ornek.pdf", b"ornek")
    )
    task = Task.objects.create(
        task_type=TaskType.objects.first(),
        title="Örnek görev",
        case=case,
        assignee=intern,
        reviewer=lawyer,
        due_date=timezone.localdate(),
    )
    TaskEvent.objects.create(task=task, actor=lawyer, kind="note", comment="Örnek görev notu")
    TaskDocument.objects.create(
        task=task,
        kind="source",
        file="tasks/ornek.pdf",
        original_name="ornek.pdf",
        uploaded_by=lawyer,
    )
    TaskPoint.objects.create(task=task, user=lawyer, points=1, earned_at=timezone.now())
    LedgerEntry.objects.create(
        client=client, case=case, kind="fee", amount=Decimal("120.00"), date=timezone.localdate()
    )
    seizure = Seizure.objects.create(case=case, debtor="Örnek borçlu", created_by=lawyer)
    SeizureRenewal.objects.create(seizure=seizure, due_date=timezone.localdate(), task=task)
    notice = PortalNotice.objects.create(
        fingerprint="uydurma", sender="Örnek", subject="Örnek tebligat"
    )
    PortalNoticeDocument.objects.create(
        notice=notice,
        source_part="1",
        content_hash="abc",
        file="notices/ornek.pdf",
        original_name="ornek.pdf",
    )
    PortalCase.objects.create(
        fingerprint="uydurma", authority="Örnek mahkeme", number="2026/1", case=case
    )
    result = office_lists.update_office_lists()
    assert not result["issues"]
    assert "ÖRNEK DOSYA" in [
        cell.value for cell in worksheet(office_directory / "Dosyalar.xlsx")[6]
    ]
    assert "ÖRNEK GÖREV" in [
        cell.value for cell in worksheet(office_directory / "Görevler.xlsx")[6]
    ]
    assert Decimal("120") in [
        cell.value for cell in worksheet(office_directory / "Muhasebe.xlsx")[6]
    ]


def test_calendar_unavailable_preserves_previous_list(office_directory, monkeypatch):
    from apps.agenda.services import AgendaResult

    assert not office_lists.update_office_lists()["issues"]
    calendar = office_directory / "Takvim.xlsx"
    before = calendar.read_bytes()
    monkeypatch.setattr(
        "apps.agenda.services.combined_events",
        lambda *args: AgendaResult(configured=True, error="Bağlantı yok"),
    )
    result = office_lists.update_office_lists()
    assert calendar.read_bytes() == before
    assert any(issue["file"] == "Takvim.xlsx" for issue in result["issues"])


def test_command_watches_and_rechecks_within_one_minute(monkeypatch):
    from types import SimpleNamespace

    from django.core.management import call_command

    from apps.core.management.commands import refresh_office_lists

    calls = []
    monkeypatch.setattr(
        refresh_office_lists, "update_office_lists", lambda: {"busy": False, "issues": []}
    )

    class StopWatching(Exception):
        pass

    def stop(seconds):
        calls.append(seconds)
        raise StopWatching

    monkeypatch.setattr(
        refresh_office_lists, "time", SimpleNamespace(monotonic=lambda: 0, sleep=stop)
    )
    with pytest.raises(StopWatching):
        call_command("refresh_office_lists", watch=True)
    assert calls == [45]


def test_individual_list_failure_does_not_stop_others(office_directory, monkeypatch):
    original = office_lists._report

    def fail_one(title, model, fields):
        if title == "Müvekkiller":
            raise RuntimeError("özel bilgi yazılmamalı")
        return original(title, model, fields)

    monkeypatch.setattr(office_lists, "_report", fail_one)
    result = office_lists.update_office_lists()
    assert (office_directory / "Dosyalar.xlsx").exists()
    assert any(
        issue == {"file": "Müvekkiller.xlsx", "reason": "Liste hazırlanamadı."}
        for issue in result["issues"]
    )
    assert "özel bilgi" not in (office_directory / office_lists.STATE_FILE).read_text(
        encoding="utf-8"
    )
