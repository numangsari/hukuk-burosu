import io
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounting.models import EntryKind, LedgerEntry
from apps.cases.models import CaseParty, Hearing, Service
from apps.clients.models import Party
from apps.office.models import TaskType
from apps.reports.base import Column, ReportResult
from apps.reports.renderers import to_xlsx
from apps.tasks import services
from apps.tasks.models import Task, TaskDocument

pytestmark = pytest.mark.django_db


def login(user):
    client = HttpClient()
    client.force_login(user)
    return client


@pytest.fixture
def task(case_factory, intern, lawyer):
    return Task.objects.create(
        task_type=TaskType.objects.get(name="Dilekçe"),
        title="Örnek dilekçe",
        case=case_factory(),
        assignee=intern,
        reviewer=lawyer,
        created_by=lawyer,
        due_date=timezone.localdate(),
    )


@pytest.mark.parametrize("role", ["intern", "lawyer", "admin_user"])
@pytest.mark.parametrize("kind", ["hearing", "service", "party"])
def test_case_record_delete_requires_admin(request, role, kind, case_factory):
    case = case_factory()
    if kind == "hearing":
        item = Hearing.objects.create(case=case, starts_at=timezone.now())
        route = "cases:hearing_delete"
    elif kind == "service":
        item = Service.objects.create(
            case=case, kind="post", subject="Örnek tebligat", served_on=timezone.localdate()
        )
        route = "cases:service_delete"
    else:
        party = Party.objects.create(kind="person", name="Örnek Karşı Taraf")
        item = CaseParty.objects.create(case=case, party=party, role="defendant")
        route = "cases:party_remove"
    client = login(request.getfixturevalue(role))
    url = reverse(route, args=[case.pk, item.pk])
    assert (url in client.get(case.get_absolute_url()).content.decode()) == (role == "admin_user")
    response = client.post(url)
    assert response.status_code == (200 if role == "admin_user" else 403)
    assert type(item).objects.filter(pk=item.pk).exists() == (role != "admin_user")


@pytest.mark.parametrize("role", ["intern", "lawyer", "admin_user"])
@pytest.mark.parametrize("kind", ["iletisim", "iban", "yetkili", "vekalet"])
def test_client_subrecord_delete_requires_admin(request, role, kind, client_factory):
    owner = (
        client_factory(kind="company", title="Örnek Şirket")
        if kind == "yetkili"
        else client_factory()
    )
    if kind == "iletisim":
        item = owner.contacts.create(kind="phone", value="0000000000")
    elif kind == "iban":
        item = owner.ibans.create(iban="TR000000000000000000000000")
    elif kind == "yetkili":
        item = owner.representatives.create(name="Örnek Yetkili")
    else:
        item = owner.powers_of_attorney.create(
            notary="Örnek Noter", date=timezone.localdate(), journal_no="1"
        )
    client = login(request.getfixturevalue(role))
    url = reverse("clients:sub_delete", args=[owner.pk, kind, item.pk])
    assert (url in client.get(owner.get_absolute_url()).content.decode()) == (role == "admin_user")
    assert client.post(url).status_code == (200 if role == "admin_user" else 403)
    assert type(item).objects.filter(pk=item.pk).exists() == (role != "admin_user")


def add_entry(owner, kind, amount):
    return LedgerEntry.objects.create(
        client=owner, kind=kind, amount=Decimal(amount), date=timezone.localdate()
    )


def test_trust_income_cannot_be_cancelled_after_payment(admin_user, client_factory):
    owner = client_factory()
    income = add_entry(owner, EntryKind.TRUST_IN, "10000")
    payment = add_entry(owner, EntryKind.TRUST_OUT, "7000")
    client = login(admin_user)
    response = client.post(
        reverse("accounting:cancel", args=[income.pk]), {"reason": "Yanlış kayıt"}
    )
    assert response.status_code == 302
    income.refresh_from_db()
    assert not income.is_cancelled
    assert owner.ledger_entries.balances()["trust"] == Decimal("3000")
    client.post(reverse("accounting:cancel", args=[payment.pk]), {"reason": "Ödeme geri alındı"})
    client.post(reverse("accounting:cancel", args=[income.pk]), {"reason": "Yanlış kayıt"})
    income.refresh_from_db()
    assert income.is_cancelled
    assert owner.ledger_entries.balances()["trust"] == 0


@pytest.mark.parametrize("linked", ["task", "ledger", "none"])
def test_case_client_change_preserves_linked_records(linked, task, client_factory, lawyer):
    case = task.case
    old_owner = case.client
    if linked != "task":
        task.delete()
    if linked == "ledger":
        LedgerEntry.objects.create(
            client=old_owner, case=case, kind="fee", amount=10, date=timezone.localdate()
        )
    new_owner = client_factory(first_name="Başka")
    response = login(lawyer).post(
        reverse("cases:update", args=[case.pk]),
        {
            "client": new_owner.pk,
            "case_type": case.case_type,
            "archive_no": case.archive_no,
            "subject": case.subject,
            "status": case.status,
            "stage": case.stage,
            "responsible_lawyer": lawyer.pk,
            "responsible_intern": case.responsible_intern_id,
        },
    )
    case.refresh_from_db()
    if linked == "none":
        assert response.status_code == 302
        assert case.client == new_owner
    else:
        assert response.status_code == 200
        assert "client" in response.context["form"].errors
        assert case.client == old_owner


@pytest.mark.parametrize("role", ["intern", "lawyer", "admin_user"])
def test_review_documents_are_frozen(request, role, task, intern, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    doc = TaskDocument.objects.create(
        task=task,
        file=SimpleUploadedFile("ornek.pdf", b"%PDF"),
        original_name="ornek.pdf",
        uploaded_by=intern,
    )
    services.perform(task, "submit", intern)
    client = login(request.getfixturevalue(role))
    assert (
        client.post(
            reverse("tasks:doc_upload", args=[task.pk]),
            {"file": SimpleUploadedFile("yeni.pdf", b"yeni"), "replaces": doc.pk},
        ).status_code
        == 403
    )
    assert client.post(reverse("tasks:doc_delete", args=[task.pk, doc.pk])).status_code == 403
    assert client.get(reverse("tasks:update", args=[task.pk])).status_code == 403
    assert task.documents.get().pk == doc.pk


def test_approve_rechecks_required_document(task, lawyer):
    Task.objects.filter(pk=task.pk).update(status="review")
    task.refresh_from_db()
    with pytest.raises(ValidationError):
        services.perform(task, "approve", lawyer)
    task.refresh_from_db()
    assert task.status == "review"
    assert not task.events.exists()
    assert not task.case.events.exists()


def test_stale_approval_does_not_publish_twice(task, intern, lawyer, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    TaskDocument.objects.create(
        task=task,
        file=SimpleUploadedFile("ornek.pdf", b"%PDF"),
        original_name="ornek.pdf",
        uploaded_by=intern,
    )
    services.perform(task, "submit", intern)
    stale_task = Task.objects.get(pk=task.pk)
    services.perform(task, "approve", lawyer)
    with pytest.raises(ValidationError):
        services.perform(stale_task, "approve", lawyer)
    assert task.events.filter(kind="approved").count() == 1
    assert task.case.documents.count() == 1
    assert task.case.events.filter(kind="task").count() == 1


def test_excel_preserves_formula_like_text():
    text = '=HYPERLINK("https://example.invalid", "Örnek")'
    result = ReportResult(
        title=text,
        subtitle=text,
        columns=[Column(text), Column("Tutar", "money")],
        rows=[[text, Decimal("123.45")]],
        totals=[text, Decimal("123.45")],
        summary=[(text, text)],
    )
    workbook = load_workbook(io.BytesIO(to_xlsx(result, text)))
    cells = [cell for row in workbook.active for cell in row if cell.value == text]
    assert len(cells) == 8
    assert all(cell.data_type == "s" for cell in cells)
    assert workbook.active.cell(9, 2).value == 123.45


def test_client_title_contains_only_text(lawyer_client, client_factory):
    response = lawyer_client.get(client_factory().get_absolute_url())
    title = response.content.decode().split("<title>", 1)[1].split("</title>", 1)[0]
    assert "<script>" not in title
    assert "DOMContentLoaded" not in title


@pytest.mark.parametrize("reason", ["", "Örnek düzeltme"])
def test_important_messages_wait_for_user_to_close(reason, admin_user, client_factory):
    entry = add_entry(client_factory(), EntryKind.FEE, "10")
    response = login(admin_user).post(
        reverse("accounting:cancel", args=[entry.pk]), {"reason": reason}, follow=True
    )
    notices = response.content.decode().split('class="toast-stack"', 1)[1]
    assert ('x-init="setTimeout' in notices) == bool(reason)
    assert 'aria-label="Bildirimi kapat"' in notices
