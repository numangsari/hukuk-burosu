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


# ---- dilekçe görevi: iş emri no -------------------------------------------------------


def petition_type():
    return TaskType.objects.filter(requires_document=True, is_active=True).first()


def plain_type():
    return (
        TaskType.objects.filter(requires_document=False, is_active=True)
        .exclude(name__iexact="Duruşma")
        .first()
    )


def task_data(case, lawyer, intern, task_type, **values):
    data = {
        "task_type": task_type.pk,
        "title": "Örnek görev",
        "client": case.client_id,
        "case": case.pk,
        "assignee": intern.pk,
        "reviewer": lawyer.pk,
        "due_date": "2026-11-10",
        "requires_accounting": "no",
        "work_order_no": "İE-2026/44",
    }
    data.update(values)
    return data


def test_petition_task_keeps_work_order_number(case_factory, lawyer, intern):
    case = case_factory()
    response = login(lawyer).post(
        reverse("tasks:create"), task_data(case, lawyer, intern, petition_type())
    )
    assert response.status_code == 302
    assert Task.objects.get().work_order_no == "İE-2026/44"


def test_work_order_number_is_dropped_for_non_petition_task_types(case_factory, lawyer, intern):
    case = case_factory()
    response = login(lawyer).post(
        reverse("tasks:create"), task_data(case, lawyer, intern, plain_type())
    )
    assert response.status_code == 302
    assert Task.objects.get().work_order_no == ""


def test_work_order_number_is_optional_and_limited(case_factory, lawyer, intern):
    case = case_factory()
    data = task_data(case, lawyer, intern, petition_type())
    data["work_order_no"] = "x" * 61
    response = login(lawyer).post(reverse("tasks:create"), data)
    assert "work_order_no" in response.context["form"].errors
    data.pop("work_order_no")
    assert login(lawyer).post(reverse("tasks:create"), data).status_code == 302
    assert Task.objects.get().work_order_no == ""


def test_work_order_number_can_be_edited_and_is_shown_on_detail(case_factory, lawyer, intern):
    case = case_factory()
    client = login(lawyer)
    client.post(reverse("tasks:create"), task_data(case, lawyer, intern, petition_type()))
    task = Task.objects.get()
    detail = client.get(task.get_absolute_url()).content.decode()
    assert "İş emri no" in detail and "İE-2026/44" in detail
    data = task_data(case, lawyer, intern, task.task_type, work_order_no="İE-2026/99")
    data.pop("document", None)
    assert client.post(reverse("tasks:update", args=[task.pk]), data).status_code == 302
    task.refresh_from_db()
    assert task.work_order_no == "İE-2026/99"


def test_task_form_offers_work_order_field(lawyer):
    html = login(lawyer).get(reverse("tasks:create")).content.decode()
    assert 'name="work_order_no"' in html and "İş emri no" in html
