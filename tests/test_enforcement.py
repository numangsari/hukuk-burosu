import datetime as dt
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import EntryKind, LedgerEntry
from apps.cases import services
from apps.cases.forms import CaseCloseForm
from apps.cases.models import CaseEvent, Seizure, SeizureRenewal
from apps.cases.seizures import create_due_tasks
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db
TODAY = dt.date(2026, 11, 1)


def close_data(**kwargs):
    data = {
        "closing_reason": "fully_collected",
        "closed_on": TODAY.isoformat(),
        "receipts-TOTAL_FORMS": "2",
        "receipts-INITIAL_FORMS": "0",
        "receipts-0-amount": "1000.25",
        "receipts-0-date": "2026-10-30",
        "receipts-0-description": "Örnek ilk ödeme",
        "receipts-1-amount": "2000",
        "receipts-1-date": TODAY.isoformat(),
        "receipts-1-description": "Örnek son ödeme",
    }
    data.update(kwargs)
    return data


def test_enforcement_close_collects_multiple_payments_once(lawyer_client, case_factory):
    case = case_factory(case_type="enforcement")
    url = reverse("cases:close", args=[case.pk])
    html = lawyer_client.get(url).content.decode()
    assert "Tahsilat ekle" in html and "closing_accounted" not in html
    assert "muhasebeye kendiliğinden işlenmez" not in html
    assert lawyer_client.post(url, close_data()).status_code == 302
    case.refresh_from_db()
    assert case.status == "closed" and case.closing_amount == Decimal("3000.25")
    entries = list(LedgerEntry.objects.filter(case=case).order_by("date"))
    assert [entry.amount for entry in entries] == [Decimal("1000.25"), Decimal("2000")]
    assert all(
        entry.kind == EntryKind.TRUST_IN and entry.client_id == case.client_id for entry in entries
    )
    assert entries[0].closing_event_id == entries[1].closing_event_id
    assert entries[0].description == "Örnek ilk ödeme"
    assert case.closing_accounted is True
    assert lawyer_client.post(url, close_data()).status_code == 302
    assert LedgerEntry.objects.filter(case=case).count() == 2
    assert case.events.filter(kind=CaseEvent.Kind.STATUS).count() == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"receipts-1-amount": "-1"},
        {"receipts-1-date": ""},
        {"receipts-1-date": "2026-11-02"},
        {"receipts-1-amount": "99999999999999.99"},
        {"receipts-TOTAL_FORMS": "101"},
    ],
)
def test_invalid_collection_keeps_case_open_and_writes_nothing(
    lawyer_client, case_factory, changes
):
    case = case_factory(case_type="enforcement")
    response = lawyer_client.post(reverse("cases:close", args=[case.pk]), close_data(**changes))
    assert response.status_code == 200
    assert "1000.25" in response.content.decode()
    case.refresh_from_db()
    assert case.is_open and not case.ledger_entries.exists() and not case.events.exists()


def test_deleted_and_empty_rows_are_not_posted(lawyer_client, case_factory):
    case = case_factory(case_type="enforcement")
    data = close_data(**{"receipts-1-DELETE": "on", "receipts-TOTAL_FORMS": "3"})
    assert lawyer_client.post(reverse("cases:close", args=[case.pk]), data).status_code == 302
    assert case.ledger_entries.count() == 1


def test_ledger_failure_rolls_back_case_event_and_all_collections(
    case_factory, lawyer, monkeypatch
):
    from apps.accounting import services as accounting

    case = case_factory(case_type="enforcement")
    form = CaseCloseForm(close_data(), case=case)
    assert form.is_valid()
    create = accounting.create_entry
    count = []

    def fail_second(entry):
        count.append(entry)
        if len(count) == 2:
            raise ValidationError("Örnek muhasebe hatası")
        return create(entry)

    monkeypatch.setattr(accounting, "create_entry", fail_second)
    with pytest.raises(services.StatusError, match="Örnek muhasebe"):
        services.close_case(
            case,
            form.cleaned_data,
            lawyer,
            collections=[{"amount": "100", "date": TODAY}, {"amount": "200", "date": TODAY}],
        )
    case.refresh_from_db()
    assert case.is_open and not case.events.exists() and not case.ledger_entries.exists()


def seizure(case, user, **kwargs):
    data = dict(
        case=case,
        debtor="Örnek borçlu",
        asset="Örnek araç",
        seized_on=TODAY - dt.timedelta(days=30),
        renewal_on=TODAY,
        created_by=user,
    )
    data.update(kwargs)
    return Seizure.objects.create(**data)


def test_seizure_renewal_date_assigns_task_once_and_catches_up(case_factory, lawyer):
    case = case_factory(case_type="enforcement")
    item = seizure(case, lawyer)
    assert create_due_tasks(TODAY - dt.timedelta(days=1)) == (0, 0)
    assert create_due_tasks(TODAY + dt.timedelta(days=2)) == (1, 0)
    task = Task.objects.get(case=case)
    assert (
        task.assignee_id == case.responsible_intern_id
        and task.reviewer_id == case.responsible_lawyer_id
    )
    assert task.due_date == TODAY and task.status == "active" and not task.assignee_seen
    assert "ÖRNEK ARAÇ" in task.title and "Örnek borçlu" in task.notes
    assert item.renewals.get().task == task
    assert create_due_tasks(TODAY + dt.timedelta(days=5)) == (0, 0)
    task.delete()
    assert create_due_tasks(TODAY + dt.timedelta(days=5)) == (0, 0)
    assert SeizureRenewal.objects.get(seizure=item).task is None


def test_new_renewal_date_keeps_old_history(case_factory, lawyer):
    case = case_factory(case_type="enforcement")
    item = seizure(case, lawyer)
    create_due_tasks(TODAY)
    item.renewal_on = TODAY + dt.timedelta(days=10)
    item.save()
    assert create_due_tasks(TODAY) == (0, 0)
    assert create_due_tasks(item.renewal_on) == (1, 0)
    assert item.renewals.count() == 2 and Task.objects.filter(case=case).count() == 2


@pytest.mark.parametrize(
    "kind, closed, active",
    [("civil", False, True), ("enforcement", True, True), ("enforcement", False, False)],
)
def test_seizures_do_not_create_unwanted_tasks(case_factory, lawyer, kind, closed, active):
    case = case_factory(case_type=kind, status="closed" if closed else "open")
    seizure(case, lawyer, is_active=active)
    assert create_due_tasks(TODAY) == (0, 0)
    assert not Task.objects.filter(case=case).exists()


def test_inactive_responsible_is_reported_until_fixed(case_factory, lawyer):
    case = case_factory(case_type="enforcement")
    seizure(case, lawyer)
    case.responsible_intern.is_active = False
    case.responsible_intern.save()
    assert create_due_tasks(TODAY) == (0, 1)
    case.responsible_intern.is_active = True
    case.responsible_intern.save()
    assert create_due_tasks(TODAY) == (1, 0)


def test_seizure_form_dates_and_case_scoping(lawyer_client, case_factory, lawyer):
    case = case_factory(case_type="enforcement")
    item = seizure(case, lawyer, renewal_on=timezone.localdate() + dt.timedelta(days=10))
    url = reverse("cases:seizure_edit", args=[case.pk, item.pk])
    assert lawyer_client.get(url).status_code == 200
    data = {
        "debtor": "Örnek kişi",
        "asset": "Örnek taşınmaz",
        "seized_on": "2026-10-02",
        "renewal_on": "2026-10-01",
        "is_active": "on",
    }
    response = lawyer_client.post(url, data)
    assert response.status_code == 200 and "renewal_on" in response.context["form"].errors
    other = case_factory(case_type="enforcement")
    assert (
        lawyer_client.post(
            reverse("cases:seizure_edit", args=[other.pk, item.pk]), data
        ).status_code
        == 404
    )
    civil = case_factory()
    assert lawyer_client.get(reverse("cases:seizure_add", args=[civil.pk])).status_code == 404
    assert "Haciz takibi" in lawyer_client.get(case.get_absolute_url()).content.decode()
    assert 'id="t-haciz"' not in lawyer_client.get(civil.get_absolute_url()).content.decode()
    data["renewal_on"] = (timezone.localdate() + dt.timedelta(days=10)).isoformat()
    assert lawyer_client.post(url, data).status_code == 302
    item.refresh_from_db()
    assert item.asset == "Örnek taşınmaz"


def test_stage_column_and_filter_do_not_mix_types(lawyer_client, case_factory):
    first = case_factory(case_type="enforcement", stage="finalized")
    second = case_factory(case_type="civil", stage="finalized")
    case_factory(case_type="enforcement", stage="seizure")
    response = lawyer_client.get(reverse("cases:list"), {"stage": "enforcement:finalized"})
    assert [case.pk for case in response.context["cases"]] == [first.pk]
    html = response.content.decode()
    assert "AŞAMA" in html and 'name="stage"' in html and "Takip kesinleşti" in html
    response = lawyer_client.get(
        reverse("cases:list"), {"stage": "civil:finalized"}, HTTP_HX_REQUEST="true"
    )
    assert [case.pk for case in response.context["cases"]] == [second.pk]


def test_authenticated_request_creates_due_tasks(case_factory, lawyer_client, lawyer):
    case = case_factory(case_type="enforcement")
    item = seizure(case, lawyer, renewal_on=timezone.localdate())
    cache.delete("seizure-tasks-check")
    assert lawyer_client.get("/").status_code == 200
    assert item.renewals.count() == 1
