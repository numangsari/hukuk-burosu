import datetime as dt
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import Document
from apps.clients.models import PowerOfAttorney
from apps.core import folders
from apps.office.models import OfficeSettings, TaskType
from apps.tasks import services
from apps.tasks.models import Task, TaskDocument

pytestmark = pytest.mark.django_db


@pytest.fixture
def office_root(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    root = tmp_path / "Ofis"
    office = OfficeSettings.load()
    office.documents_root = str(root)
    office.save()
    return root


@pytest.fixture
def task(case_factory, lawyer, intern):
    case = case_factory(archive_no="2026/0041", subject="Alacak davası")
    tt = TaskType.objects.get(name="Dilekçe")  # belge zorunlu tür
    return Task.objects.create(
        task_type=tt, title="Cevap dilekçesi", case=case, assignee=intern, reviewer=lawyer,
        due_date=timezone.localdate() + dt.timedelta(days=3), created_by=lawyer,
    )  # fmt: skip


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def upload(c, task, name="dilekce.docx", content=b"icerik", replaces=""):
    return c.post(
        reverse("tasks:doc_upload", args=[task.pk]),
        {"file": SimpleUploadedFile(name, content), "replaces": replaces},
    )


def test_sanitize():
    assert folders.sanitize('2026/0041 - Alacak: "X" davası?') == "2026-0041 - Alacak- -X- davası-"
    assert folders.sanitize("CON") == "CON_"
    assert folders.sanitize("  ad.  ") == "ad"


def test_requires_document_before_submit(task, intern, office_root):
    with pytest.raises(ValidationError):
        services.perform(task, "submit", intern)
    upload(login(intern), task)
    services.perform(task, "submit", intern)
    assert task.status == "review"


def test_versions_and_permissions(task, intern, lawyer, client_factory, office_root):
    c = login(intern)
    upload(c, task, "dilekce.docx", b"v1")
    first = TaskDocument.objects.get()
    upload(c, task, "dilekce-duzeltilmis.docx", b"v2", replaces=first.pk)
    first.refresh_from_db()
    current = TaskDocument.objects.get(is_current=True)
    assert not first.is_current and current.version == 2 and current.previous == first
    # Kontrolcü de yükleyebilir; ilgisiz kullanıcı yükleyemez.
    assert upload(login(lawyer), task, "not.pdf").status_code == 200
    from .conftest import make_user

    assert upload(login(make_user("baska", "lawyer")), task).status_code == 403
    # Güncel sürüm silinince önceki sürüm güncel olur.
    c.post(reverse("tasks:doc_delete", args=[task.pk, current.pk]))
    first.refresh_from_db()
    assert first.is_current


def test_approve_publishes_to_case_and_folder(task, intern, lawyer, office_root):
    upload(login(intern), task, "dilekce.docx", b"son hal")
    services.perform(task, "submit", intern)
    services.perform(task, "approve", lawyer)
    assert task.warnings == []
    doc = Document.objects.get(case=task.case)
    assert doc.category == "petition" and doc.title == "CEVAP DİLEKÇESİ"
    folder = (
        office_root
        / "Müvekkiller"
        / f"M{task.case.client_id:06d} - DENEME KİŞİ"
        / f"D{task.case_id:06d} - 2026-0041 - ALACAK DAVASI"
    )
    files = list(folder.iterdir())
    assert len(files) == 1 and files[0].read_bytes() == b"son hal"
    assert files[0].name == f"{timezone.localdate():%Y-%m-%d} CEVAP DİLEKÇESİ.docx"
    assert doc.folder_path == str(files[0])


def test_existing_client_folder_is_reused_and_names_not_overwritten(
    case_factory, lawyer_client, office_root
):
    existing = office_root / "Müvekkiller" / "DENEME KİŞİ"
    existing.mkdir(parents=True)
    case = case_factory(archive_no="7", subject="İhtar")
    case.client.folder_name = "DENEME KİŞİ"
    case.client.save(update_fields=["folder_name"])
    case.folder_name = "7 - İhtar"
    case.save(update_fields=["folder_name"])
    url = reverse("cases:document_upload", args=[case.pk])
    for _ in range(2):
        lawyer_client.post(
            url,
            {
                "title": "İhtarname",
                "category": "other",
                "file": SimpleUploadedFile("ihtar.pdf", b"x"),
            },
        )
    case.client.refresh_from_db()
    assert case.client.folder_name == "DENEME KİŞİ"
    names = sorted(p.name for p in (existing / "7 - İhtar").iterdir())
    assert names == ["ihtar (2).pdf", "ihtar.pdf"]


def test_poa_pdf_goes_to_vekaletler(client_factory, lawyer_client, office_root):
    c = client_factory()
    from tests.conftest import client_form_data

    row = {"notary": "Sakarya 1. Noterliği", "date": "2026-10-01", "journal_no": "12345",
           "pdf": SimpleUploadedFile("vekalet.pdf", b"%PDF")}  # fmt: skip
    lawyer_client.post(reverse("clients:update", args=[c.pk]), client_form_data(c, vekalet=[row]))
    poa = PowerOfAttorney.objects.get()
    assert Path(poa.folder_path).parent.name == "Vekaletler"
    assert Path(poa.folder_path).name == "2026-10-01 Sakarya 1. Noterliği 12345.pdf"


def test_no_root_gives_warning_but_still_saves(task, intern, lawyer, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    upload(login(intern), task)
    services.perform(task, "submit", intern)
    services.perform(task, "approve", lawyer)
    assert Document.objects.filter(case=task.case).exists()
    assert "Ofis klasörü ayarlanmadığı" in task.warnings[0]


def test_settings_documents_root_validation(admin_user, tmp_path):
    c = login(admin_user)
    url = reverse("accounts:settings")
    r = c.post(url, {"section": "klasor", "documents_root": "goreli/yol"})
    assert "documents_root" in r.context["forms"]["klasor"].errors
    c.post(url, {"section": "klasor", "documents_root": str(tmp_path / "Ofis")})
    assert OfficeSettings.load().documents_root == str(tmp_path / "Ofis")
    assert (tmp_path / "Ofis").is_dir()


def test_task_type_settings_formset(admin_user):
    tt = TaskType.objects.get(name="Müvekkil görüşmesi")
    qs = list(TaskType.objects.all())
    data = {"section": "gorev_turleri", "tt-TOTAL_FORMS": len(qs) + 1, "tt-INITIAL_FORMS": len(qs)}
    for i, t in enumerate(qs):
        data.update({f"tt-{i}-id": t.pk, f"tt-{i}-name": t.name, f"tt-{i}-order": t.order})
        if t.is_active:
            data[f"tt-{i}-is_active"] = "on"
        if t.requires_document or t.pk == tt.pk:
            data[f"tt-{i}-requires_document"] = "on"
    data.update(
        {f"tt-{len(qs)}-name": "Temyiz", f"tt-{len(qs)}-order": 99, f"tt-{len(qs)}-is_active": "on"}
    )
    r = login(admin_user).post(reverse("accounts:settings"), data)
    assert r.status_code == 302
    tt.refresh_from_db()
    assert tt.requires_document and TaskType.objects.filter(name="Temyiz").exists()
