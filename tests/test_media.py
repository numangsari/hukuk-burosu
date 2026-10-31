import datetime as dt
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import LedgerEntry
from apps.cases.models import Document
from apps.office.models import OfficeSettings, TaskType
from apps.tasks.models import Task, TaskDocument

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


def login(user=None):
    c = HttpClient()
    if user:
        c.force_login(user)
    return c


def make_doc(case, name, content=b"x"):
    d = Document(case=case, title=name, original_name=name)
    d.file.save(name, ContentFile(content), save=False)
    d.save()
    return d


def test_case_document_requires_login_and_pdf_inline(case_factory, lawyer):
    doc = make_doc(case_factory(), "dilekce.pdf", b"%PDF-1.4")
    url = doc.file.url
    assert login().get(url).status_code == 302  # girişsiz yönlendirilir
    r = login(lawyer).get(url)
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert not r.get("Content-Disposition", "").startswith("attachment")
    assert r["X-Content-Type-Options"] == "nosniff"


def test_non_preview_types_are_downloaded(case_factory, lawyer):
    doc = make_doc(case_factory(), "dilekce.docx")
    r = login(lawyer).get(doc.file.url)
    assert r["Content-Disposition"].startswith("attachment")
    assert "sandbox" in r["Content-Security-Policy"]


def test_ledger_receipt_needs_accounting_permission(client_factory, lawyer, intern):
    c = client_factory()
    e = LedgerEntry(client=c, kind="expense", amount=Decimal("10"), date=dt.date(2026, 11, 1))
    e.receipt.save("makbuz.pdf", ContentFile(b"%PDF"), save=False)
    e.save()
    assert not OfficeSettings.load().intern_can_view_accounting
    assert login(intern).get(e.receipt.url).status_code == 403
    assert login(lawyer).get(e.receipt.url).status_code == 200


def test_stray_unknown_and_traversal_paths_404(media, lawyer):
    (media / "cases" / "1").mkdir(parents=True)
    (media / "cases" / "1" / "sahipsiz.pdf").write_bytes(b"%PDF")
    (media / "imports" / "tmp").mkdir(parents=True)
    (media / "imports" / "tmp" / "a.xlsx").write_bytes(b"PK")
    c = login(lawyer)
    assert c.get("/media/cases/1/sahipsiz.pdf").status_code == 404  # kayda bağlı değil
    assert c.get("/media/imports/tmp/a.xlsx").status_code == 404
    assert c.get("/media/cases/../../settings.py").status_code == 404


def test_office_logo_public(media):
    office = OfficeSettings.load()
    office.logo.save("logo.png", ContentFile(b"\x89PNG"), save=True)
    assert login().get(office.logo.url).status_code == 200


def test_dangerous_uploads_rejected(case_factory, client_factory, lawyer_client, intern, lawyer):
    case = case_factory()
    r = lawyer_client.post(
        reverse("cases:document_upload", args=[case.pk]),
        {"title": "x", "category": "other", "file": SimpleUploadedFile("kotu.html", b"<script>")},
    )
    assert "file" in r.context["document_form"].errors and not Document.objects.exists()
    r = lawyer_client.post(
        reverse("clients:sub_add", args=[case.client_id, "vekalet"]),
        {
            "notary": "N",
            "date": "2026-10-01",
            "journal_no": "1",
            "pdf": SimpleUploadedFile("v.svg", b"<svg/>"),
        },
    )
    assert "pdf" in r.context["form"].errors
    task = Task.objects.create(
        task_type=TaskType.objects.get(name="Müvekkil görüşmesi"), title="t", case=case, assignee=intern,
        reviewer=lawyer, due_date=timezone.localdate(), created_by=lawyer,
    )  # fmt: skip
    login(intern).post(
        reverse("tasks:doc_upload", args=[task.pk]), {"file": SimpleUploadedFile("a.exe", b"MZ")}
    )
    assert not TaskDocument.objects.exists()
    login(intern).post(
        reverse("tasks:doc_upload", args=[task.pk]),
        {"file": SimpleUploadedFile("dilekce.udf", b"x")},
    )
    assert TaskDocument.objects.count() == 1  # UYAP belgesi kabul edilir
