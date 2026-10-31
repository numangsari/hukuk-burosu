import datetime

import pytest
from django.test import Client as HttpClient
from django.urls import reverse

from apps.cases.models import CaseParty
from apps.clients.conflicts import clients_matching, parties_matching
from apps.clients.models import Client, Party, PowerOfAttorney

from .conftest import VALID_TCKN

pytestmark = pytest.mark.django_db


def test_login_required(client):
    r = client.get(reverse("clients:list"))
    assert r.status_code == 302
    assert reverse("accounts:login") in r.url


def test_client_name_and_search_key(client_factory):
    c = client_factory(first_name="Işık", last_name="Çelik")
    assert c.name == "Işık Çelik"
    assert c.search_key == "isik celik"
    co = client_factory(kind="company", title="ABC Ticaret A.Ş.", first_name="x", last_name="y")
    assert co.name == "ABC Ticaret A.Ş."
    assert co.first_name == ""


def test_create_person_client(lawyer_client, lawyer, intern):
    r = lawyer_client.post(
        reverse("clients:create"),
        {
            "kind": "person",
            "first_name": "Ayşe",
            "last_name": "Yılmaz",
            "tckn": VALID_TCKN,
            "responsible_lawyer": lawyer.pk,
            "responsible_intern": intern.pk,
            "is_active": "on",
        },
    )
    assert r.status_code == 302
    c = Client.objects.get()
    assert c.created_by == lawyer
    assert c.tckn == VALID_TCKN


def test_person_requires_names(lawyer_client, lawyer, intern):
    r = lawyer_client.post(
        reverse("clients:create"),
        {"kind": "person", "responsible_lawyer": lawyer.pk, "responsible_intern": intern.pk},
    )
    assert r.status_code == 200
    assert not Client.objects.exists()


def test_intern_cannot_be_responsible_lawyer(lawyer_client, intern):
    r = lawyer_client.post(
        reverse("clients:create"),
        {
            "kind": "person",
            "first_name": "A",
            "last_name": "B",
            "responsible_lawyer": intern.pk,
            "responsible_intern": intern.pk,
        },
    )
    assert r.status_code == 200
    assert "responsible_lawyer" in r.context["form"].errors


def test_conflict_blocks_until_confirmed(lawyer_client, lawyer, intern, case_factory):
    party = Party.objects.create(kind="person", name="Mehmet Demir")
    CaseParty.objects.create(case=case_factory(), party=party, role="defendant")
    data = {
        "kind": "person",
        "first_name": "MEHMET",
        "last_name": "DEMİR",
        "responsible_lawyer": lawyer.pk,
        "responsible_intern": intern.pk,
    }
    r = lawyer_client.post(reverse("clients:create"), data)
    assert r.status_code == 200
    assert r.context["form"].conflicts == [party]
    assert Client.objects.count() == 1  # yalnızca case_factory'nin müvekkili

    r = lawyer_client.post(reverse("clients:create"), {**data, "confirm_conflict": "on"})
    assert r.status_code == 302
    assert Client.objects.filter(search_key="mehmet demir").exists()


def test_conflict_by_identity_no(client_factory):
    Party.objects.create(kind="person", name="Farklı Ad", identity_no=VALID_TCKN)
    assert len(parties_matching("Başka", VALID_TCKN)) == 1
    client_factory(tckn=VALID_TCKN)
    assert len(clients_matching("Herhangi", VALID_TCKN)) == 1


def test_list_filters(lawyer_client, client_factory, case_factory):
    a = client_factory(first_name="Ali", last_name="Kaya")
    b = client_factory(kind="company", title="Beta Ltd")
    case_factory(client=a)
    case_factory(client=a)
    PowerOfAttorney.objects.create(
        client=b, notary="1. Noter", date=datetime.date(2026, 1, 1), journal_no="1"
    )

    url = reverse("clients:list")
    names = lambda r: [c.name for c in r.context["clients"]]  # noqa: E731
    assert names(lawyer_client.get(url, {"kind": "company"})) == ["Beta Ltd"]
    assert names(lawyer_client.get(url, {"poa": "yes"})) == ["Beta Ltd"]
    assert names(lawyer_client.get(url, {"poa": "no"})) == ["Ali Kaya"]
    assert names(lawyer_client.get(url, {"q": "KAYA"})) == ["Ali Kaya"]
    r = lawyer_client.get(url, {"sort": "-case_count"})
    assert names(r)[0] == "Ali Kaya"
    assert r.context["clients"][0].case_count == 2


def test_list_htmx_returns_partial(lawyer_client, client_factory):
    client_factory()
    r = lawyer_client.get(reverse("clients:list"), HTTP_HX_REQUEST="true")
    assert [t.name for t in r.templates][0] == "clients/_list_table.html"


def test_subrecord_add_iban_and_primary(lawyer_client, client_factory):
    c = client_factory()
    url = reverse("clients:sub_add", args=[c.pk, "iban"])
    lawyer_client.post(url, {"iban": "TR33 0006 1005 1978 6457 8413 26", "is_primary": "on"})
    lawyer_client.post(url, {"iban": "TR330006100519786457841326", "is_primary": "on"})
    ibans = list(c.ibans.order_by("id"))
    assert ibans[0].iban == "TR330006100519786457841326"
    assert [i.is_primary for i in ibans] == [False, True]


def test_only_admin_can_delete(lawyer, admin_user, client_factory):
    c = client_factory()
    url = reverse("clients:delete", args=[c.pk])
    as_lawyer, as_admin = HttpClient(), HttpClient()
    as_lawyer.force_login(lawyer)
    as_admin.force_login(admin_user)
    assert as_lawyer.post(url).status_code == 403
    assert as_admin.post(url).status_code == 302
    assert not Client.objects.filter(pk=c.pk).exists()


def test_delete_protected_by_cases(admin_client_logged, case_factory):
    case = case_factory()
    admin_client_logged.post(reverse("clients:delete", args=[case.client_id]))
    assert Client.objects.filter(pk=case.client_id).exists()
