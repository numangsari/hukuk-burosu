import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client as HttpClient
from django.urls import reverse

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounting.views import statement
from apps.cases.models import CaseType

pytestmark = pytest.mark.django_db
D = Decimal


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def add(client, kind, amount, case=None, **kw):
    return LedgerEntry.objects.create(
        client=client, case=case, kind=kind, amount=D(amount), date=dt.date(2026, 11, 1), **kw
    )


def test_excluded_entry_not_in_balance_but_kept(client_factory, case_factory):
    c = client_factory()
    case = case_factory(client=c)
    add(c, EntryKind.FEE, "1000", case=case)
    bad = add(c, EntryKind.EXPENSE, "500", case=case, portal_ref="x1", excluded_from_balance=True)
    assert c.ledger_entries.balances()["balance"] == D("1000")
    assert c.ledger_entries.totals_by_kind()[EntryKind.EXPENSE] == D("0")
    rows = statement(c.ledger_entries.all())
    assert [r["balance"] for r in rows] == [D("1000"), D("1000")]
    assert LedgerEntry.objects.filter(pk=bad.pk).exists()


def test_exclude_requires_permission_and_reason(admin_user, intern, client_factory, case_factory):
    c = client_factory()
    case = case_factory(client=c)
    entry = add(c, EntryKind.EXPENSE, "500", case=case, portal_ref="x2")
    url = reverse("accounting:exclude", args=[entry.pk])
    # Stajyerde yetki yok.
    assert login(intern).post(url, {"reason": "hatalı"}).status_code == 403
    entry.refresh_from_db()
    assert not entry.excluded_from_balance
    # Gerekçesiz olmaz.
    admin = login(admin_user)
    admin.post(url, {"reason": " "})
    entry.refresh_from_db()
    assert not entry.excluded_from_balance
    # Gerekçeyle olur, geri alınır.
    admin.post(url, {"reason": "UYAP hatalı aktardı"})
    entry.refresh_from_db()
    assert entry.excluded_from_balance and entry.excluded_by == admin_user
    assert c.ledger_entries.balances()["balance"] == D("0")
    admin.post(url, {"action": "include"})
    entry.refresh_from_db()
    assert not entry.excluded_from_balance and entry.exclude_reason == ""


def test_only_portal_entries_can_be_excluded(admin_user, client_factory, case_factory):
    c = client_factory()
    entry = add(c, EntryKind.FEE, "100", case=case_factory(client=c))
    r = login(admin_user).post(reverse("accounting:exclude", args=[entry.pk]), {"reason": "deneme"})
    assert r.status_code == 404
    entry.refresh_from_db()
    assert not entry.excluded_from_balance


def test_case_ledger_tab_splits_sources_and_hides_uyap_for_contracts(
    admin_user, client_factory, case_factory
):
    c = client_factory()
    litigation = case_factory(client=c)
    add(c, EntryKind.FEE, "1000", case=litigation, description="büro ücreti")
    add(c, EntryKind.EXPENSE, "200", case=litigation, description="uyap harcı", portal_ref="x3")
    admin = login(admin_user)
    r = admin.get(litigation.get_absolute_url())
    assert r.context["ledger_split"] is True
    assert len(r.context["ledger_office_rows"]) == 1
    assert len(r.context["ledger_portal_rows"]) == 1
    assert r.context["ledger_balances"]["balance"] == D("1200")

    contract = case_factory(client=c, case_type=CaseType.CONSULTANCY)
    r = admin.get(contract.get_absolute_url())
    assert r.context["ledger_split"] is False
    assert b"UYAP (salt okunur)" not in r.content.split(b'id="t-muhasebe"')[1]
