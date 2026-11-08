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


SIGNATURES = {".pdf": b"%PDF-1.4\n", ".docx": b"PK\x03\x04"}


def signed(name, content):
    """Yükleme denetimini geçmesi için içeriğin başına uzantıya uygun dosya imzası ekler."""
    return SIGNATURES.get(Path(name).suffix.lower(), b"") + content


def upload(c, task, name="dilekce.docx", content=b"icerik", replaces=""):
    return c.post(
        reverse("tasks:doc_upload", args=[task.pk]),
        {"file": SimpleUploadedFile(name, signed(name, content)), "replaces": replaces},
    )


def test_sanitize():
    assert folders.sanitize('2026/0041 - Alacak: "X" davası?') == "2026-0041 - Alacak- -X- davası-"
    assert folders.sanitize("CON") == "CON_"
    assert folders.sanitize("  ad.  ") == "ad"


def test_requires_document_before_submit(task, intern, office_root):
    with pytest.raises(ValidationError):
        services.perform(task, "submit", intern, "Not")
    upload(login(intern), task)
    services.perform(task, "submit", intern, "Not")
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
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    assert task.warnings == []
    doc = Document.objects.get(case=task.case)
    assert doc.category == "petition" and doc.title == "CEVAP DİLEKÇESİ"
    folder = office_root / "Müvekkiller" / "DENEME KİŞİ" / "ALACAK DAVASI"
    published = folder / f"{timezone.localdate():%Y-%m-%d} CEVAP DİLEKÇESİ.docx"
    assert published.read_bytes() == signed("x.docx", b"son hal")
    assert (folder / "Görevler" / "dilekce.docx").read_bytes() == signed("x.docx", b"son hal")
    assert doc.folder_path == str(published)


def test_document_on_task_creation_is_stored_and_copied(
    case_factory, lawyer, intern, office_root, django_capture_on_commit_callbacks
):
    case = case_factory(subject="Örnek dosya")
    task_type = TaskType.objects.get(name="Dava Dosyası İnceleme")
    data = {
        "task_type": task_type.pk,
        "title": "Dava dosyası inceleme",
        "client": case.client_id,
        "case": case.pk,
        "assignee": intern.pk,
        "reviewer": lawyer.pk,
        "due_date": "2026-11-10",
        "requires_accounting": "yes",
        "document": [
            SimpleUploadedFile("ornek.pdf", signed("a.pdf", b"ornek belge")),
            SimpleUploadedFile("diger.pdf", signed("a.pdf", b"ikinci belge")),
        ],
    }
    with django_capture_on_commit_callbacks(execute=True):
        response = login(lawyer).post(reverse("tasks:create"), data)
    assert response.status_code == 302
    docs = list(TaskDocument.objects.filter(task__case=case).order_by("original_name"))
    assert [doc.original_name for doc in docs] == ["diger.pdf", "ornek.pdf"]
    assert all(doc.uploaded_by == lawyer for doc in docs)
    assert all(Path(doc.folder_path).parent.name == "Görevler" for doc in docs)
    assert [Path(doc.folder_path).read_bytes() for doc in docs] == [
        signed("a.pdf", b"ikinci belge"),
        signed("a.pdf", b"ornek belge"),
    ]


def test_invalid_document_does_not_create_task(case_factory, lawyer, intern, office_root):
    case = case_factory()
    response = login(lawyer).post(
        reverse("tasks:create"),
        {
            "task_type": TaskType.objects.get(name="Dava Dosyası İnceleme").pk,
            "title": "Örnek",
            "client": case.client_id,
            "case": case.pk,
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "due_date": "2026-11-10",
            "document": SimpleUploadedFile("tehlikeli.html", b"ornek"),
        },
    )
    assert response.status_code == 200
    assert "document" in response.context["form"].errors
    assert not Task.objects.filter(case=case).exists()


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
                "file": SimpleUploadedFile("ihtar.pdf", signed("a.pdf", b"x")),
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
           "pdf": SimpleUploadedFile("vekalet.pdf", b"%PDF-1.4")}  # fmt: skip
    lawyer_client.post(reverse("clients:update", args=[c.pk]), client_form_data(c, vekalet=[row]))
    poa = PowerOfAttorney.objects.get()
    assert Path(poa.folder_path).parent.name == "Vekaletler"
    assert Path(poa.folder_path).name == "2026-10-01 Sakarya 1. Noterliği 12345.pdf"


def test_no_root_gives_warning_but_still_saves(task, intern, lawyer, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    upload(login(intern), task)
    services.perform(task, "submit", intern, "Not")
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
    tt = TaskType.objects.get(name="Müvekkil Görüşmesi")
    qs = list(TaskType.objects.all())
    data = {"section": "gorev_turleri", "tt-TOTAL_FORMS": len(qs) + 1, "tt-INITIAL_FORMS": len(qs)}
    for i, t in enumerate(qs):
        data.update(
            {
                f"tt-{i}-id": t.pk,
                f"tt-{i}-name": t.name,
                f"tt-{i}-order": t.order,
                f"tt-{i}-points": t.points,
            }
        )
        if t.is_active:
            data[f"tt-{i}-is_active"] = "on"
        if t.requires_document or t.pk == tt.pk:
            data[f"tt-{i}-requires_document"] = "on"
    data.update(
        {
            f"tt-{len(qs)}-name": "Temyiz",
            f"tt-{len(qs)}-order": 99,
            f"tt-{len(qs)}-points": 1,
            f"tt-{len(qs)}-is_active": "on",
        }
    )
    r = login(admin_user).post(reverse("accounts:settings"), data)
    assert r.status_code == 302
    tt.refresh_from_db()
    assert tt.requires_document and TaskType.objects.filter(name="Temyiz").exists()


def test_source_document_is_protected_and_does_not_satisfy_petition_requirement(
    task, intern, lawyer, office_root
):
    document = TaskDocument.objects.create(
        task=task,
        kind=TaskDocument.Kind.SOURCE,
        file=SimpleUploadedFile("kaynak.pdf", b"kaynak"),
        original_name="kaynak.pdf",
        uploaded_by=lawyer,
    )
    client = login(lawyer)
    assert client.post(reverse("tasks:doc_delete", args=[task.pk, document.pk])).status_code == 403
    assert upload(client, task, replaces=document.pk).status_code == 403
    with pytest.raises(ValidationError):
        services.perform(task, "submit", intern, "Not")
    assert TaskDocument.objects.filter(pk=document.pk).exists()
    response = client.get(task.case.client.get_absolute_url())
    assert "kaynak.pdf" in response.content.decode()
    response = client.get(task.case.get_absolute_url())
    assert "kaynak.pdf" in response.content.decode()


def test_task_documents_and_petitions_are_in_separate_sections(task, intern, lawyer, office_root):
    TaskDocument.objects.create(
        task=task,
        kind=TaskDocument.Kind.SOURCE,
        file=SimpleUploadedFile("kaynak.pdf", b"kaynak"),
        original_name="kaynak.pdf",
        uploaded_by=lawyer,
    )
    upload(login(intern), task, "dilekce.pdf")
    response = login(lawyer).get(task.get_absolute_url())
    html = response.content.decode()
    assert html.index("Dilekçeler") < html.index("dilekce.pdf") < html.index("Görev belgeleri")
    assert html.index("Görev belgeleri") < html.index("kaynak.pdf")


def test_non_pdf_petition_has_only_one_download_button(task, intern, lawyer, office_root):
    upload(login(intern), task, "ornek.udf")
    response = login(lawyer).get(task.get_absolute_url())
    html = response.content.decode()
    row = html.split("ornek.udf", 1)[1].split("</li>", 1)[0]
    assert row.count("download>") == 1
    assert ">Aç</a>" not in row
