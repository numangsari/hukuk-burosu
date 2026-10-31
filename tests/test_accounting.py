import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client as HttpClient
from django.urls import reverse

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounting.views import statement
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db
D = Decimal


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def add(client, kind, amount, case=None, **kw):
    return LedgerEntry.objects.create(
        client=client,
        case=case,
        kind=kind,
        amount=D(amount),
        date=kw.pop("date", dt.date(2026, 11, 1)),
        **kw,
    )


def test_balance_formulas_example_from_spec(client_factory):
    """Planlamadaki örnek: 50.000 ücret, 5.000 masraf, 20.000 tahsilat,
    100.000 karşı taraftan tahsilat, 70.000 müvekkile ödeme."""
    c = client_factory()
    add(c, EntryKind.FEE, "50000")
    add(c, EntryKind.EXPENSE, "5000")
    add(c, EntryKind.COLLECTION, "20000")
    add(c, EntryKind.TRUST_IN, "100000")
    add(c, EntryKind.TRUST_OUT, "70000")
    b = c.ledger_entries.balances()
    assert (b["cari"], b["trust"], b["net"]) == (D("35000"), D("30000"), D("5000"))

    add(c, EntryKind.OFFSET, "30000")  # emanetteki 30.000 cari borçtan düşülür
    b = c.ledger_entries.balances()
    assert (b["cari"], b["trust"], b["net"]) == (D("5000"), D("0"), D("5000"))


def test_cancelled_entries_excluded(client_factory):
    c = client_factory()
    add(c, EntryKind.FEE, "1000")
    add(c, EntryKind.FEE, "500", is_cancelled=True)
    assert c.ledger_entries.balances()["cari"] == D("1000")


def test_statement_running_balances(client_factory):
    c = client_factory()
    add(c, EntryKind.FEE, "1000", date=dt.date(2026, 1, 1))
    add(c, EntryKind.TRUST_IN, "400", date=dt.date(2026, 1, 2))
    add(c, EntryKind.OFFSET, "300", date=dt.date(2026, 1, 3))
    rows = statement(c.ledger_entries.all())
    assert [(r["cari"], r["trust"]) for r in rows] == [
        (D("700"), D("100")),
        (D("1000"), D("400")),
        (D("1000"), D("0")),
    ]


def test_create_entry_case_sets_client_and_trust_limits(admin_user, case_factory):
    case = case_factory()
    c = login(admin_user)
    url = reverse("accounting:create")
    r = c.post(url, {"kind": "fee", "case": case.pk, "amount": "15000.50", "date": "2026-11-01"})
    assert r.status_code == 302
    e = LedgerEntry.objects.get()
    assert e.client == case.client and e.created_by == admin_user

    # Emanet yokken müvekkile ödeme / mahsup yapılamaz.
    r = c.post(
        url, {"kind": "trust_out", "client": case.client_id, "amount": "10", "date": "2026-11-01"}
    )
    assert "amount" in r.context["form"].errors
    r = c.post(
        url, {"kind": "offset", "client": case.client_id, "amount": "10", "date": "2026-11-01"}
    )
    assert "amount" in r.context["form"].errors
    assert LedgerEntry.objects.count() == 1


def test_case_must_belong_to_client(admin_user, case_factory, client_factory):
    case = case_factory()
    other = client_factory(first_name="Diğer")
    r = login(admin_user).post(
        reverse("accounting:create"),
        {"kind": "fee", "client": other.pk, "case": case.pk, "amount": "10", "date": "2026-11-01"},
    )
    assert "case" in r.context["form"].errors


def test_cancel_requires_reason_and_edit_right(admin_user, lawyer, client_factory):
    c = client_factory()
    e = add(c, EntryKind.FEE, "100")
    url = reverse("accounting:cancel", args=[e.pk])
    office = OfficeSettings.load()
    office.lawyer_can_edit_accounting = False
    office.save()
    assert login(lawyer).post(url, {"reason": "hata"}).status_code == 403
    login(admin_user).post(url, {"reason": ""})
    e.refresh_from_db()
    assert not e.is_cancelled
    login(admin_user).post(url, {"reason": "Yanlış tutar"})
    e.refresh_from_db()
    assert e.is_cancelled and e.cancelled_by == admin_user and e.cancel_reason == "Yanlış tutar"


def test_role_permissions(lawyer, intern, client_factory):
    c = client_factory()
    add(c, EntryKind.FEE, "100")
    # Varsayılan: avukat görür ve girer, stajyer göremez.
    assert login(lawyer).get(reverse("accounting:list")).status_code == 200
    assert login(intern).get(reverse("accounting:list")).status_code == 403
    r = login(intern).get(reverse("clients:list"))
    assert "Bakiye" not in r.content.decode()
    r = login(intern).get(reverse("clients:list"), {"sort": "-balance", "debt": "yes"})
    assert r.status_code == 200 and len(r.context["clients"]) == 1  # filtre yok sayılır

    office = OfficeSettings.load()
    office.intern_can_view_accounting = True
    office.save()
    assert login(intern).get(reverse("accounting:list")).status_code == 200
    assert login(intern).get(reverse("accounting:create")).status_code == 403


def test_client_list_balance_tasks_and_filters(lawyer_client, client_factory, case_factory):
    from apps.office.models import TaskType
    from apps.tasks.models import Task

    a = client_factory(first_name="Borçlu")
    b = client_factory(first_name="Temiz")
    add(a, EntryKind.FEE, "2000")
    add(a, EntryKind.COLLECTION, "500")
    add(b, EntryKind.FEE, "100")
    add(b, EntryKind.COLLECTION, "100")
    case = case_factory(client=a)
    Task.objects.create(
        task_type=TaskType.objects.first(), title="x", case=case, assignee=case.responsible_intern,
        reviewer=case.responsible_lawyer, due_date=dt.date(2026, 11, 5),
    )  # fmt: skip
    url = reverse("clients:list")
    rows = {c.first_name: c for c in lawyer_client.get(url).context["clients"]}
    assert rows["Borçlu"].balance == D("1500") and rows["Borçlu"].open_task_count == 1
    assert rows["Temiz"].balance == D("0") and rows["Temiz"].open_task_count == 0
    names = lambda r: [c.first_name for c in r.context["clients"]]  # noqa: E731
    assert names(lawyer_client.get(url, {"debt": "yes"})) == ["Borçlu"]
    assert names(lawyer_client.get(url, {"tasks": "yes"})) == ["Borçlu"]
    assert names(lawyer_client.get(url, {"sort": "-balance"}))[0] == "Borçlu"


def test_detail_tabs_show_statement(lawyer_client, case_factory):
    case = case_factory()
    add(case.client, EntryKind.FEE, "750", case=case)
    html = lawyer_client.get(case.client.get_absolute_url()).content.decode()
    assert "Cari hesap ekstresi" in html and "750,00 ₺" in html
    html = lawyer_client.get(case.get_absolute_url()).content.decode()
    assert "Dosya hareketleri" in html


def test_permissions_form_edit_requires_view(admin_user):
    login(admin_user).post(
        reverse("accounts:settings"),
        {
            "section": "yetkiler",
            "lawyer_can_view_accounting": "",
            "lawyer_can_edit_accounting": "on",
        },
    )
    office = OfficeSettings.load()
    assert not office.lawyer_can_view_accounting and not office.lawyer_can_edit_accounting
