import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounting.views import statement

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
    assert (b["debt"], b["credit"], b["balance"]) == (D("55000"), D("100000"), D("5000"))


def test_cancelled_entries_excluded(client_factory):
    c = client_factory()
    add(c, EntryKind.FEE, "1000")
    add(c, EntryKind.FEE, "500", is_cancelled=True, cancelled_at=timezone.now())
    assert c.ledger_entries.balances()["balance"] == D("1000")


def test_statement_running_balances(client_factory):
    c = client_factory()
    add(c, EntryKind.FEE, "1000", date=dt.date(2026, 1, 1))
    add(c, EntryKind.TRUST_IN, "400", date=dt.date(2026, 1, 2))
    add(c, EntryKind.TRUST_OUT, "300", date=dt.date(2026, 1, 3))
    rows = statement(c.ledger_entries.all())
    assert [r["balance"] for r in rows] == [D("900"), D("600"), D("1000")]


def test_offset_kind_removed():
    assert "offset" not in EntryKind.values


def test_create_entry_requires_client_case_optional_no_trust_limit(admin_user, case_factory):
    case = case_factory()
    c = login(admin_user)
    url = reverse("accounting:create")
    # Müvekkil seçmeden kayıt girilemez.
    r = c.post(url, {"kind": "fee", "case": case.pk, "amount": "10", "date": "2026-11-01"})
    assert "client" in r.context["form"].errors and not LedgerEntry.objects.exists()
    r = c.post(
        url,
        {"kind": "fee", "client": case.client_id, "case": case.pk, "amount": "15000.50",
         "date": "2026-11-01"},
    )  # fmt: skip
    assert r.status_code == 302
    e = LedgerEntry.objects.get()
    assert e.client == case.client and e.case == case and e.created_by == admin_user
    # Dosya seçmeden müvekkilin genel gideri girilebilir.
    r = c.post(
        url, {"kind": "expense", "client": case.client_id, "amount": "50", "date": "2026-11-01"}
    )
    assert r.status_code == 302
    assert LedgerEntry.objects.filter(case__isnull=True, kind="expense").count() == 1
    LedgerEntry.objects.filter(kind="expense").delete()

    # Karşı taraftan tahsilat yetmese de müvekkile ödeme yapılabilir.
    for kind in ("trust_out",):
        r = c.post(
            url, {"kind": kind, "client": case.client_id, "amount": "10", "date": "2026-11-01"}
        )
        assert r.status_code == 302
    assert LedgerEntry.objects.count() == 2


def test_case_must_belong_to_client(admin_user, case_factory, client_factory):
    case = case_factory()
    other = client_factory(first_name="Diğer")
    r = login(admin_user).post(
        reverse("accounting:create"),
        {"kind": "fee", "client": other.pk, "case": case.pk, "amount": "10", "date": "2026-11-01"},
    )
    assert "case" in r.context["form"].errors


def test_cancel_requires_reason(admin_user, intern, client_factory):
    c = client_factory(responsible_lawyer=admin_user, responsible_intern=None)
    e = add(c, EntryKind.FEE, "100")
    url = reverse("accounting:cancel", args=[e.pk])
    login(admin_user).post(url, {"reason": ""})
    e.refresh_from_db()
    assert not e.is_cancelled
    # Sorumlu olmayan stajyer iptal edemez; yönetici edebilir.
    assert login(intern).post(url, {"reason": "Yanlış tutar"}).status_code == 403
    e.refresh_from_db()
    assert not e.is_cancelled
    login(admin_user).post(url, {"reason": "Yanlış tutar"})
    e.refresh_from_db()
    assert e.is_cancelled and e.cancelled_by == admin_user and e.cancel_reason == "Yanlış tutar"


def test_cancel_allowed_for_file_responsible(admin_user, case_factory, client_factory):
    case = case_factory()
    mine = add(case.client, EntryKind.FEE, "100", case=case)
    foreign_case = case_factory(
        client=client_factory(
            first_name="Başka", responsible_lawyer=admin_user, responsible_intern=None
        )
    )
    foreign = add(foreign_case.client, EntryKind.FEE, "100", case=foreign_case)
    c = login(case.responsible_lawyer)
    assert (
        c.post(reverse("accounting:cancel", args=[foreign.pk]), {"reason": "x"}).status_code == 403
    )
    c.post(reverse("accounting:cancel", args=[mine.pk]), {"reason": "Hatalı"})
    mine.refresh_from_db()
    assert mine.is_cancelled


def test_records_for_everyone_balances_for_selected(lawyer, intern, client_factory, case_factory):
    case = case_factory()
    add(case.client, EntryKind.FEE, "100", case=case)
    # Kayıtlar herkese açık: stajyer muhasebe listesini görür ve kayıt girebilir.
    assert login(intern).get(reverse("accounting:list")).status_code == 200
    assert login(intern).get(reverse("accounting:create")).status_code == 200
    html = login(intern).get(case.get_absolute_url()).content.decode()
    assert "Dosya hareketleri" in html
    # Bakiye ve borçluluk yalnızca yöneticiye ve seçilen kişilere görünür.
    r = login(lawyer).get(reverse("clients:list"))
    assert "Bakiye" not in r.content.decode()
    r = login(lawyer).get(reverse("clients:list"), {"sort": "-balance", "debt": "yes"})
    assert r.status_code == 200 and len(r.context["clients"]) == 1  # süzgeç yok sayılır
    assert (
        "Hesap ekstresi" not in login(lawyer).get(case.client.get_absolute_url()).content.decode()
    )
    from apps.office.models import OfficeSettings

    OfficeSettings.load().set_role_permission("accounting.balances", ["accountant", "lawyer"])
    assert "Bakiye" in login(lawyer).get(reverse("clients:list")).content.decode()


def test_client_list_balance_tasks_and_filters(lawyer, client_factory, case_factory):
    from apps.office.models import OfficeSettings, TaskType
    from apps.tasks.models import Task

    OfficeSettings.load().set_role_permission("accounting.balances", ["accountant", "lawyer"])
    lawyer_client = login(lawyer)
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
    assert rows["BORÇLU"].balance == D("1500") and rows["BORÇLU"].open_task_count == 1
    assert rows["TEMİZ"].balance == D("0") and rows["TEMİZ"].open_task_count == 0
    names = lambda r: [c.first_name for c in r.context["clients"]]  # noqa: E731
    assert names(lawyer_client.get(url, {"debt": "yes"})) == ["BORÇLU"]
    assert names(lawyer_client.get(url, {"sort": "-balance"}))[0] == "BORÇLU"


def test_detail_tabs_show_statement(admin_user, case_factory):
    case = case_factory()
    add(case.client, EntryKind.FEE, "750", case=case)
    c = login(admin_user)
    html = c.get(case.client.get_absolute_url()).content.decode()
    assert "Hesap ekstresi" in html and "750,00 ₺" in html
    html = c.get(case.get_absolute_url()).content.decode()
    assert "Dosya hareketleri" in html


def test_permission_matrix_saves_role_choices(admin_user, lawyer, intern):
    from apps.core.permission_registry import has_perm

    assert not has_perm(intern, "accounting.balances")
    r = login(admin_user).post(
        reverse("accounts:settings"),
        {
            "section": "yetkiler",
            "perm:accounting.balances:intern": "on",
            "perm:accounting.balances:accountant": "on",
        },
    )
    assert r.status_code == 302
    assert has_perm(intern, "accounting.balances") and not has_perm(lawyer, "accounting.balances")
    # İşaretlenmeyen yetkiler yönetici dışında herkesten alınır; yönetici kilitlidir.
    assert not has_perm(lawyer, "tasks.edit_any") and has_perm(admin_user, "tasks.edit_any")


def test_settings_sections_render(admin_user, intern):
    c = login(admin_user)
    r = c.get(reverse("accounts:settings"), {"bolum": "yetkiler"})
    html = r.content.decode()
    assert r.status_code == 200 and "Roller ve yetkiler" in html
    assert "Tebligattan görev oluşturma" in html and "yok sayma" in html
    assert (
        'name="perm:cases.view_all:lawyer"' in html
        and 'name="perm:cases.view_all:admin"' not in html
    )
    r = c.get(reverse("accounts:settings"), {"bolum": "kullanicilar", "id": intern.pk})
    assert r.status_code == 200 and "Kontrolcü" in r.content.decode()


def test_cancelled_entries_only_in_history_tab(admin_user, case_factory):
    case = case_factory()
    kept = add(case.client, EntryKind.FEE, "800", case=case)
    gone = add(
        case.client,
        EntryKind.EXPENSE,
        "123",
        case=case,
        is_cancelled=True,
        cancelled_at=timezone.now(),
    )
    c = login(admin_user)
    for url in (case.get_absolute_url(), case.client.get_absolute_url()):
        response = c.get(url)
        assert [r["entry"].pk for r in response.context["ledger_rows"]] == [kept.pk]
        assert [e.pk for e in response.context["cancelled_entries"]] == [gone.pk]
        assert "İptal edilen muhasebe hareketleri" in response.content.decode()


@pytest.mark.parametrize("amount", ["0", "-5"])
def test_database_rejects_non_positive_amount(client_factory, amount):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        add(client_factory(), EntryKind.EXPENSE, amount)


def test_database_rejects_cancel_without_time(client_factory):
    from django.db import IntegrityError, transaction

    entry = add(client_factory(), EntryKind.EXPENSE, "10")
    with pytest.raises(IntegrityError), transaction.atomic():
        LedgerEntry.objects.filter(pk=entry.pk).update(is_cancelled=True)
