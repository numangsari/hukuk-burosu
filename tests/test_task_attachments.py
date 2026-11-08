import datetime as dt
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import Document
from apps.office.models import OfficeSettings, TaskType
from apps.tasks import services
from apps.tasks.models import Task, TaskDocument

pytestmark = pytest.mark.django_db

SIGNATURES = {".pdf": b"%PDF-1.4\n", ".docx": b"PK\x03\x04"}


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
    case = case_factory(archive_no="2026/0077", subject="Alacak davası")
    return Task.objects.create(
        task_type=TaskType.objects.get(name="Dilekçe"),
        title="Cevap dilekçesi",
        case=case,
        assignee=intern,
        reviewer=lawyer,
        due_date=timezone.localdate() + dt.timedelta(days=3),
        created_by=lawyer,
    )


def login(user):
    client = HttpClient()
    client.force_login(user)
    return client


def signed(name, content):
    return SIGNATURES.get(Path(name).suffix.lower(), b"") + content


def upload(client, task, name, content=b"icerik", kind=None):
    data = {"file": SimpleUploadedFile(name, signed(name, content))}
    if kind:
        data["kind"] = kind
    return client.post(reverse("tasks:doc_upload", args=[task.pk]), data)


def test_attachment_is_stored_with_its_own_kind(task, intern, office_root):
    response = upload(login(intern), task, "ek-1.pdf", kind="attachment")
    assert response.status_code == 200
    document = TaskDocument.objects.get()
    assert document.kind == TaskDocument.Kind.ATTACHMENT
    assert document.version == 1 and document.is_current


def test_unknown_kind_falls_back_to_petition(task, intern, office_root):
    upload(login(intern), task, "dilekce.docx", kind="gizli")
    assert TaskDocument.objects.get().kind == TaskDocument.Kind.PETITION


def test_attachment_alone_does_not_satisfy_petition_requirement(task, intern, office_root):
    upload(login(intern), task, "ek-1.pdf", kind="attachment")
    with pytest.raises(ValidationError):
        services.perform(task, "submit", intern, "Not")
    upload(login(intern), task, "dilekce.docx")
    services.perform(task, "submit", intern, "Not")
    assert task.status == "review"


def test_attachment_cannot_replace_a_petition_version(task, intern, office_root):
    client = login(intern)
    upload(client, task, "dilekce.docx")
    petition = TaskDocument.objects.get()
    response = client.post(
        reverse("tasks:doc_upload", args=[task.pk]),
        {
            "file": SimpleUploadedFile("ek.pdf", signed("ek.pdf", b"x")),
            "kind": "attachment",
            "replaces": petition.pk,
        },
    )
    assert response.status_code == 403
    petition.refresh_from_db()
    assert petition.is_current


def test_attachments_are_listed_apart_from_petitions_and_sources(task, intern, office_root):
    client = login(intern)
    upload(client, task, "dilekce.docx")
    upload(client, task, "ek-1.pdf", kind="attachment")
    context = client.get(task.get_absolute_url()).context
    assert [d.original_name for d in context["petition_docs"]] == ["dilekce.docx"]
    assert [d.original_name for d in context["attachment_docs"]] == ["ek-1.pdf"]
    assert context["source_docs"] == []


def test_attachment_can_be_deleted_by_uploader_while_active(task, intern, office_root):
    client = login(intern)
    upload(client, task, "ek-1.pdf", kind="attachment")
    document = TaskDocument.objects.get()
    response = client.post(reverse("tasks:doc_delete", args=[task.pk, document.pk]))
    assert response.status_code == 200
    assert not TaskDocument.objects.exists()


def test_attachment_is_copied_to_task_folder(task, intern, office_root):
    upload(login(intern), task, "ek-1.pdf", kind="attachment")
    document = TaskDocument.objects.get()
    assert Path(document.folder_path).parent.name == "Görevler"


def test_approval_publishes_petition_and_attachments_to_case(task, intern, lawyer, office_root):
    client = login(intern)
    upload(client, task, "dilekce.docx", b"son hal")
    upload(client, task, "ek-1.pdf", b"ek bir", kind="attachment")
    upload(client, task, "ek-2.pdf", b"ek iki", kind="attachment")
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    assert task.warnings == []
    documents = Document.objects.filter(case=task.case).order_by("title")
    assert len(documents) == 3
    attachments = [d for d in documents if "ek-" in d.original_name]
    assert len(attachments) == 2
    assert all("Ek" in d.title for d in attachments)
    assert all("dilekçe eki" in d.notes for d in attachments)
    petition = next(d for d in documents if d.original_name == "dilekce.docx")
    assert petition.title == "CEVAP DİLEKÇESİ" and "eki" not in petition.notes
    published = {p.name for p in office_root.rglob("*") if p.is_file()}
    assert any(name.endswith("CEVAP DİLEKÇESİ.docx") for name in published)
    assert len([n for n in published if n.endswith(".pdf")]) >= 2


def test_older_attachment_versions_are_not_published(task, intern, lawyer, office_root):
    client = login(intern)
    upload(client, task, "dilekce.docx")
    upload(client, task, "ek-1.pdf", kind="attachment")
    TaskDocument.objects.filter(kind="attachment").update(is_current=False)
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    assert Document.objects.filter(case=task.case).count() == 1
