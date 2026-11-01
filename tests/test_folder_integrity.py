from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core import folders
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def office_root(tmp_path):
    root = tmp_path / "Ofis"
    office = OfficeSettings.load()
    office.documents_root = str(root)
    office.save()
    return root


@pytest.mark.parametrize("other_name", ["ÖRNEK", "ORNEK"])
def test_same_names_use_separate_numbered_folders(client_factory, office_root, other_name):
    first = client_factory(first_name="Örnek", last_name="Kişi")
    second = client_factory(first_name=other_name, last_name="Kişi")
    first_path = folders.client_dir(first)
    second_path = folders.client_dir(second)
    assert first_path.name == "ÖRNEK KİŞİ"
    assert second_path.name == f"{other_name} KİŞİ (2)"
    assert first_path != second_path


def test_unassigned_legacy_folder_is_not_matched_by_name(client_factory, office_root):
    legacy = office_root / "Müvekkiller" / "Deneme Kişi"
    legacy.mkdir(parents=True)
    (legacy / "eski.txt").write_bytes(b"onceki belge")
    owner = client_factory()
    target = folders.client_dir(owner)
    assert target != legacy
    assert list(target.iterdir()) == []
    assert (legacy / "eski.txt").read_bytes() == b"onceki belge"


def test_saved_legacy_folder_is_preserved(client_factory, office_root):
    legacy = office_root / "Müvekkiller" / "ESKİ KLASÖR"
    legacy.mkdir(parents=True)
    owner = client_factory(folder_name="Eski Klasör")
    assert folders.client_dir(owner) == legacy
    owner.refresh_from_db()
    assert owner.folder_name == "ESKİ KLASÖR"


@pytest.mark.parametrize(
    "first_folder, other_folder",
    [
        ("Ortak", "Ortak"),
        ("Ortak", "ORTAK"),
        ("Ortak", "Örtak"),
        ("A/B", "A:B"),
    ],
)
def test_shared_client_folder_blocks_new_copies(
    client_factory, office_root, first_folder, other_folder
):
    first = client_factory(folder_name=first_folder)
    client_factory(first_name="Başka", folder_name=other_folder)
    with pytest.raises(folders.FolderError, match="başka bir müvekkil"):
        folders.client_dir(first)
    assert not office_root.exists()


def test_ambiguous_existing_folders_require_explicit_resolution(client_factory, office_root):
    for name in ["Ornek", "Örnek"]:
        (office_root / "Müvekkiller" / name).mkdir(parents=True)
    owner = client_factory(folder_name="Ornek")
    with pytest.raises(folders.FolderError, match="birden fazla klasör"):
        folders.client_dir(owner)


def test_same_case_names_remain_separate(case_factory, office_root):
    first = case_factory(archive_no="26/1", subject="Örnek")
    second = case_factory(client=first.client, archive_no="26-1", subject="Örnek")
    first_path = folders.case_dir(first)
    second_path = folders.case_dir(second)
    assert first_path.name == "ÖRNEK"
    assert second_path.name == "ÖRNEK (2)"
    assert first_path != second_path


def test_shared_case_folder_blocks_new_copies(case_factory, office_root):
    first = case_factory(folder_name="Ortak")
    case_factory(client=first.client, folder_name="ORTAK")
    with pytest.raises(folders.FolderError, match="başka bir dosya"):
        folders.case_dir(first)


def test_same_case_folder_name_is_allowed_for_different_clients(case_factory, office_root):
    first = case_factory(folder_name="Eski Dosya")
    second = case_factory(folder_name="Eski Dosya")
    assert folders.case_dir(first) != folders.case_dir(second)


def test_case_cannot_share_power_of_attorney_folder(case_factory, office_root):
    case = case_factory(folder_name="Vekaletler")
    with pytest.raises(folders.FolderError, match="Vekaletler"):
        folders.case_dir(case)


def test_stale_client_object_keeps_stored_folder(client_factory, office_root):
    owner = client_factory()
    stale = type(owner).objects.get(pk=owner.pk)
    first_path = folders.client_dir(owner)
    stale.first_name = "Yeni ad"
    stale.save(update_fields=["first_name", "name", "search_key"])
    assert folders.client_dir(stale) == first_path


def test_parallel_file_copies_keep_both_contents(tmp_path, monkeypatch):
    barrier, state = Barrier(2), local()
    choose_path = folders.unique_path

    def choose_together(directory, filename):
        target = choose_path(directory, filename)
        if not getattr(state, "waited", False):
            state.waited = True
            barrier.wait(timeout=10)
        return target

    monkeypatch.setattr(folders, "unique_path", choose_together)

    def copy(content):
        return folders.copy_file(SimpleUploadedFile("ornek.txt", content), tmp_path, "ornek.txt")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(copy, content) for content in (b"birinci", b"ikinci")]
        paths = [future.result(timeout=20) for future in futures]
    assert len(set(paths)) == 2
    assert {path.read_bytes() for path in paths} == {b"birinci", b"ikinci"}


def test_client_company_uses_title_and_case_uses_official_name(
    client_factory, case_factory, office_root
):
    owner = client_factory(kind="company", title="Örnek Şirket")
    case = case_factory(
        client=owner, authority="Sakarya 3. Asliye Hukuk Mahkemesi", official_no="2026/121"
    )
    path = folders.case_dir(case)
    assert path.parent.name == "ÖRNEK ŞİRKET"
    assert path.name == "SAKARYA 3. ASLİYE HUKUK MAHKEMESİ - 2026-121 Esas"


def test_new_folder_read_error_is_reported(client_factory, office_root, monkeypatch):
    from pathlib import Path

    parent = office_root / folders.CLIENTS_DIR
    parent.mkdir(parents=True)
    owner = client_factory()
    iterdir = Path.iterdir

    def denied(path):
        if path == parent:
            raise PermissionError("Örnek erişim hatası")
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", denied)
    with pytest.raises(folders.FolderError, match="okunamadı"):
        folders.client_dir(owner)
