import datetime as dt
import io
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.cases.models import Document
from apps.clients.models import PowerOfAttorney, RetainerAgreement
from apps.core import folders
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def legacy(case_factory, tmp_path):
    base = tmp_path / "Ofis"
    office = OfficeSettings.load()
    office.documents_root = str(base)
    office.save()
    case = case_factory(
        folder_name="D0001 - Eski", authority="Örnek Mahkeme", official_no="2026/121"
    )
    owner = case.client
    owner.folder_name = "M0001 - Eski"
    owner.save(update_fields=["folder_name"])
    client_path = base / folders.CLIENTS_DIR / owner.folder_name
    case_path = client_path / case.folder_name
    case_path.mkdir(parents=True)
    document_path = case_path / "örnek.pdf"
    document_path.write_bytes(b"dosya")
    doc = Document.objects.create(case=case, title="Örnek belge", folder_path=str(document_path))
    poa_path = client_path / folders.POA_DIR / "vekalet.pdf"
    poa_path.parent.mkdir()
    poa_path.write_bytes(b"vekalet")
    poa = PowerOfAttorney.objects.create(
        client=owner,
        notary="Örnek Noter",
        date=dt.date(2026, 11, 1),
        journal_no="1",
        folder_path=str(poa_path),
    )
    agreement_path = client_path / folders.RETAINER_DIR / "sozlesme.pdf"
    agreement_path.parent.mkdir()
    agreement_path.write_bytes(b"sozlesme")
    agreement = RetainerAgreement.objects.create(
        client=owner, signed_on=dt.date(2026, 11, 1), folder_path=str(agreement_path)
    )
    return base, owner, case, doc, poa, agreement


def test_preview_then_apply_preserves_contents_and_updates_all_paths(legacy):
    base, owner, case, doc, poa, agreement = legacy
    old_parent = base / folders.CLIENTS_DIR / owner.folder_name
    call_command("rename_document_folders", stdout=io.StringIO())
    owner.refresh_from_db()
    assert owner.folder_name == "M0001 - Eski" and old_parent.exists()
    call_command("rename_document_folders", apply=True, stdout=io.StringIO())
    owner.refresh_from_db()
    case.refresh_from_db()
    assert owner.folder_name == owner.name
    assert case.folder_name == "ÖRNEK MAHKEME - 2026-121 Esas"
    for item, content in [(doc, b"dosya"), (poa, b"vekalet"), (agreement, b"sozlesme")]:
        item.refresh_from_db()
        assert Path(item.folder_path).read_bytes() == content
        assert Path(item.folder_path).is_relative_to(base / folders.CLIENTS_DIR / owner.name)
    assert not old_parent.exists()
    call_command("rename_document_folders", apply=True, stdout=io.StringIO())
    assert folders.case_dir(case).is_dir()


def test_existing_target_is_not_merged(legacy):
    base, owner, case, doc, *_ = legacy
    occupied = base / folders.CLIENTS_DIR / owner.name
    occupied.mkdir()
    (occupied / "dokunma.txt").write_bytes(b"ayri")
    call_command("rename_document_folders", apply=True, stdout=io.StringIO())
    owner.refresh_from_db()
    doc.refresh_from_db()
    assert owner.folder_name == owner.name + " (2)"
    assert (occupied / "dokunma.txt").read_bytes() == b"ayri"
    assert Path(doc.folder_path).read_bytes() == b"dosya"


def test_move_failure_rolls_back_folders_and_database(legacy, monkeypatch):
    base, owner, case, doc, *_ = legacy
    old_parent = base / folders.CLIENTS_DIR / owner.folder_name
    old_doc_path = doc.folder_path
    rename = Path.rename
    calls = []

    def fail_on_second(source, target):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("Örnek taşıma hatası")
        return rename(source, target)

    monkeypatch.setattr(Path, "rename", fail_on_second)
    with pytest.raises(CommandError, match="eski yerlerine"):
        call_command("rename_document_folders", apply=True, stdout=io.StringIO())
    owner.refresh_from_db()
    case.refresh_from_db()
    doc.refresh_from_db()
    assert owner.folder_name == "M0001 - Eski"
    assert case.folder_name == "D0001 - Eski"
    assert doc.folder_path == old_doc_path
    assert old_parent.exists() and Path(old_doc_path).read_bytes() == b"dosya"


def test_outside_root_folder_is_rejected_without_moving(legacy, tmp_path):
    base, owner, case, *_ = legacy
    outside = tmp_path / "Disarisi"
    outside.mkdir()
    case.folder_name = "Ayrı"
    case.save(update_fields=["folder_name"])
    link = base / folders.CLIENTS_DIR / owner.folder_name / "Ayrı"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Bu ortam sembolik bağlantı oluşturamıyor.")
    with pytest.raises(CommandError, match="belge kökünün dışında"):
        call_command("rename_document_folders", apply=True, stdout=io.StringIO())
    assert outside.is_dir()


def test_database_failure_rolls_back_client_and_case_moves(legacy, monkeypatch):
    from django.db.models.query import QuerySet

    base, owner, case, doc, *_ = legacy
    old_path = doc.folder_path
    update = QuerySet.update

    def fail_document_update(query, **kwargs):
        if query.model is Document:
            raise RuntimeError("Örnek kayıt hatası")
        return update(query, **kwargs)

    monkeypatch.setattr(QuerySet, "update", fail_document_update)
    with pytest.raises(CommandError, match="eski yerlerine"):
        call_command("rename_document_folders", apply=True, stdout=io.StringIO())
    owner.refresh_from_db()
    case.refresh_from_db()
    doc.refresh_from_db()
    assert owner.folder_name == "M0001 - Eski" and case.folder_name == "D0001 - Eski"
    assert doc.folder_path == old_path and Path(old_path).read_bytes() == b"dosya"


def test_missing_folder_is_prepared_without_creating_or_losing_files(legacy):
    base, owner, case, doc, *_ = legacy
    missing = type(case).objects.create(
        client=owner,
        case_type="civil",
        archive_no="Eski-2",
        subject="Eksik klasör",
        authority="Başka Mahkeme",
        official_no="2026/2",
        folder_name="Eksik eski klasör",
        responsible_lawyer=case.responsible_lawyer,
        responsible_intern=case.responsible_intern,
    )
    output = io.StringIO()
    call_command("rename_document_folders", apply=True, stdout=output)
    missing.refresh_from_db()
    doc.refresh_from_db()
    assert missing.folder_name == "BAŞKA MAHKEME - 2026-2 Esas"
    assert "1 klasör diskte yok" in output.getvalue()
    assert Path(doc.folder_path).read_bytes() == b"dosya"
    assert folders.case_dir(missing).is_dir()


def test_path_outside_root_is_rejected(tmp_path):
    from apps.core.management.commands.rename_document_folders import checked_path

    base = tmp_path / "Ofis"
    base.mkdir()
    with pytest.raises(CommandError, match="belge kökünün dışında"):
        checked_path(base.resolve(), tmp_path / "Başka klasör")
