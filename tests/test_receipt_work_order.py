import pytest
from django.test import Client
from django.urls import reverse

from apps.accounting.models import EntryKind, LedgerEntry
from apps.office.models import TaskType
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def login(user):
    client = Client()
    client.force_login(user)
    return client


def entry_data(case, **values):
    data = {
        "kind": "expense",
        "client": case.client_id,
        "case": case.pk,
        "amount": "100",
        "date": "2026-11-01",
        "receipt_no": "MKB-2026-17",
    }
    data.update(values)
    return data


# ---- gider: makbuz no ----------------------------------------------------------------


def test_expense_keeps_receipt_number(admin_user, case_factory):
    case = case_factory()
    response = login(admin_user).post(
        reverse("accounting:create"), entry_data(case, receipt_no="  MKB-17 ")
    )
    assert response.status_code == 302
    assert LedgerEntry.objects.get().receipt_no == "MKB-17"


@pytest.mark.parametrize("kind", [value for value in EntryKind.values if value != "expense"])
def test_receipt_number_is_dropped_for_other_entry_kinds(admin_user, case_factory, kind):
    case = case_factory()
    response = login(admin_user).post(reverse("accounting:create"), entry_data(case, kind=kind))
    assert response.status_code == 302
    assert LedgerEntry.objects.get().receipt_no == ""


def test_receipt_number_is_optional(admin_user, case_factory):
    case = case_factory()
    data = entry_data(case)
    data.pop("receipt_no")
    assert login(admin_user).post(reverse("accounting:create"), data).status_code == 302
    assert LedgerEntry.objects.get().receipt_no == ""


def test_receipt_number_has_a_length_limit(admin_user, case_factory):
    case = case_factory()
    response = login(admin_user).post(
        reverse("accounting:create"), entry_data(case, receipt_no="x" * 61)
    )
    assert "receipt_no" in response.context["form"].errors
    assert not LedgerEntry.objects.exists()


def test_receipt_number_is_shown_in_list_and_client_statement(admin_user, case_factory):
    case = case_factory()
    login(admin_user).post(reverse("accounting:create"), entry_data(case))
    client = login(admin_user)
    assert "MKB-2026-17" in client.get(reverse("accounting:list")).content.decode()
    assert "MKB-2026-17" in client.get(case.client.get_absolute_url()).content.decode()


def test_entry_form_offers_receipt_number_field(admin_user):
    html = login(admin_user).get(reverse("accounting:create")).content.decode()
    assert 'name="receipt_no"' in html and "Makbuz no" in html


# ---- görev kapatılırken iş emri no ve makbuz no (zorunlu değil) -------------------------


def make_task(case, lawyer, intern, **kw):
    from django.utils import timezone

    defaults = {
        "task_type": TaskType.objects.get(name="Müvekkil Görüşmesi"),
        "title": "Örnek görev",
        "case": case,
        "assignee": intern,
        "reviewer": None,
        "due_date": timezone.localdate(),
        "created_by": lawyer,
    }
    defaults.update(kw)
    return Task.objects.create(**defaults)


def add_petition(task, user):
    from django.core.files.base import ContentFile

    from apps.tasks.models import TaskDocument

    doc = TaskDocument(task=task, kind="petition", original_name="d.pdf", size=9, uploaded_by=user)
    doc.file.save("d.pdf", ContentFile(b"%PDF-1.4 x"), save=False)
    doc.save()


def close(client, task, **extra):
    return client.post(
        reverse("tasks:action", args=[task.pk]), {"action": "close", "comment": "Bitti", **extra}
    )


def test_task_form_no_longer_asks_work_order_number(lawyer):
    html = login(lawyer).get(reverse("tasks:create")).content.decode()
    assert 'name="work_order_no"' not in html


def test_work_order_number_saved_at_close_for_petition_tasks(case_factory, lawyer, intern):
    task = make_task(case_factory(), lawyer, intern, requires_document=True)
    add_petition(task, lawyer)
    detail = login(intern).get(task.get_absolute_url()).content.decode()
    assert 'name="work_order_no"' in detail and 'name="receipt_no"' not in detail
    close(login(intern), task, work_order_no=" İE-2026/44 ")
    task.refresh_from_db()
    assert task.work_order_no == "İE-2026/44"
    assert "İş emri no" in login(intern).get(task.get_absolute_url()).content.decode()


def test_work_order_number_is_optional_and_dropped_without_petition(case_factory, lawyer, intern):
    petition = make_task(case_factory(), lawyer, intern, requires_document=True)
    add_petition(petition, lawyer)
    assert close(login(intern), petition).status_code == 302
    petition.refresh_from_db()
    assert petition.status == "done" and petition.work_order_no == ""
    plain = make_task(case_factory(), lawyer, intern, requires_document=False)
    close(login(intern), plain, work_order_no="İE-1")
    plain.refresh_from_db()
    assert plain.work_order_no == ""


def test_receipt_number_saved_at_close_for_accounting_tasks(case_factory, lawyer, intern):
    case = case_factory()
    entry = LedgerEntry.objects.create(
        client=case.client, case=case, kind="expense", amount=10, date="2026-11-01"
    )
    task = make_task(case, lawyer, intern, requires_accounting=True)
    detail = login(intern).get(task.get_absolute_url()).content.decode()
    assert 'name="receipt_no"' in detail
    close(login(intern), task, ledger_id=entry.pk, receipt_no="MKB-9")
    task.refresh_from_db()
    assert task.receipt_no == "MKB-9" and task.status == "done"
    other = make_task(case, lawyer, intern, requires_accounting=False)
    close(login(intern), other, receipt_no="MKB-1")
    other.refresh_from_db()
    assert other.receipt_no == ""


def test_numbers_have_a_length_limit(case_factory, lawyer, intern):
    task = make_task(case_factory(), lawyer, intern, requires_document=True)
    add_petition(task, lawyer)
    close(login(intern), task, work_order_no="x" * 61)
    task.refresh_from_db()
    assert task.status == "active"
