import datetime

import pytest
from django.test import Client as HttpClient
from django.urls import reverse

from apps.clients.models import Client, PowerOfAttorney

from .conftest import VALID_TCKN, client_form_data

pytestmark = pytest.mark.django_db


def formsets(**rows):
    """Müvekkil formundaki alt kayıt gruplarının yönetim alanları (+ isteğe bağlı satırlar)."""
    data = {}
    for prefix in ("iletisim", "iban", "yetkili", "vekalet", "sozlesme"):
        items = rows.get(prefix, [])
        data[f"{prefix}-TOTAL_FORMS"] = str(len(items))
        data[f"{prefix}-INITIAL_FORMS"] = "0"
        for i, item in enumerate(items):
            data.update({f"{prefix}-{i}-{k}": v for k, v in item.items()})
    return data


def test_login_required(client):
    r = client.get(reverse("clients:list"))
    assert r.status_code == 302
    assert reverse("accounts:login") in r.url


def test_client_name_and_search_key(client_factory):
    c = client_factory(first_name="Işık", last_name="Çelik")
    assert c.name == "IŞIK ÇELİK"  # adlar her zaman büyük harf
    assert c.search_key == "isik celik"
    co = client_factory(kind="company", title="ABC Ticaret A.Ş.", first_name="x", last_name="y")
    assert co.name == "ABC TİCARET A.Ş."
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
            **formsets(
                iletisim=[{"kind": "phone", "value": "0532 000 00 00"}],
                iban=[{"iban": "TR33 0006 1005 1978 6457 8413 26"}],
                vekalet=[{"notary": "1. Noter", "date": "2026-01-02", "journal_no": "55"}],
            ),
        },
    )
    assert r.status_code == 302
    c = Client.objects.get()
    assert c.created_by == lawyer
    assert c.tckn == VALID_TCKN
    assert c.name == "AYŞE YILMAZ"
    # İletişim, IBAN ve vekalet aynı ekrandan kaydedilir; vekaleti olana V-numarası verilir.
    assert c.contacts.count() == 1 and c.ibans.count() == 1
    assert c.powers_of_attorney.count() == 1 and c.poa_label == "V-1"


def test_person_create_in_window_refreshes_parent(lawyer_client, lawyer, intern):
    response = lawyer_client.post(
        reverse("clients:create") + "?pencere=1",
        {
            "kind": "person",
            "first_name": "Deneme",
            "last_name": "Kişi",
            "tckn": VALID_TCKN,
            "responsible_lawyer": lawyer.pk,
            "responsible_intern": intern.pk,
            **formsets(),
        },
    )
    assert response.status_code == 200
    assert "window.parent.location.reload()" in response.content.decode()
    assert Client.objects.filter(first_name="DENEME").exists()


def test_person_requires_names(lawyer_client, lawyer, intern):
    r = lawyer_client.post(
        reverse("clients:create"),
        {
            "kind": "person",
            "responsible_lawyer": lawyer.pk,
            "responsible_intern": intern.pk,
            **formsets(),
        },
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
            **formsets(),
        },
    )
    assert r.status_code == 200
    assert "responsible_lawyer" in r.context["form"].errors


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
    assert names(lawyer_client.get(url, {"kind": "company"})) == ["BETA LTD"]
    assert names(lawyer_client.get(url, {"poa": "yes"})) == ["BETA LTD"]
    assert names(lawyer_client.get(url, {"poa": "no"})) == ["ALİ KAYA"]
    assert names(lawyer_client.get(url, {"q": "kaya"})) == ["ALİ KAYA"]
    r = lawyer_client.get(url, {"sort": "-case_count"})
    assert names(r)[0] == "ALİ KAYA"
    assert r.context["clients"][0].case_count == 2


def test_list_htmx_returns_partial(lawyer_client, client_factory):
    client_factory()
    r = lawyer_client.get(reverse("clients:list"), HTTP_HX_REQUEST="true")
    assert [t.name for t in r.templates][0] == "clients/_list_table.html"


def test_edit_form_keeps_single_primary_iban(lawyer_client, client_factory):
    c = client_factory()
    c.ibans.create(iban="TR330006100519786457841326", is_primary=True)
    url = reverse("clients:update", args=[c.pk])
    data = client_form_data(
        c, iban=[{"iban": "TR33 0006 1005 1978 6457 8413 26", "is_primary": "on"}]
    )
    assert lawyer_client.post(url, data).status_code == 302
    ibans = list(c.ibans.order_by("id"))
    assert [i.is_primary for i in ibans] == [False, True]


def test_party_with_client_name_needs_no_confirmation(client_factory, case_factory, lawyer_client):
    case = case_factory()
    url = reverse("cases:party_add", args=[case.pk])
    lawyer_client.post(url, {"role": "defendant", "kind": "person", "name": case.client.name})
    assert case.party_links.count() == 1  # çıkar çatışması uyarısı kaldırıldı


def test_only_admin_can_delete(lawyer, admin_user, client_factory):
    c = client_factory()
    url = reverse("clients:delete", args=[c.pk])
    as_lawyer, as_admin = HttpClient(), HttpClient()
    as_lawyer.force_login(lawyer)
    as_admin.force_login(admin_user)
    assert as_lawyer.get(url).status_code == 403
    assert as_lawyer.post(url, {"confirm": "1"}).status_code == 403
    # Onay kutusu işaretlenmeden silinmez.
    as_admin.post(url)
    assert Client.objects.filter(pk=c.pk).exists()
    assert as_admin.post(url, {"confirm": "1"}).status_code == 302
    assert not Client.objects.filter(pk=c.pk).exists()


def test_delete_client_with_cases_removes_related(admin_client_logged, case_factory):
    from apps.accounting.models import LedgerEntry
    from apps.office.models import TaskType
    from apps.tasks.models import Task

    case = case_factory()
    client = case.client
    Task.objects.create(
        task_type=TaskType.objects.first(), title="x", case=case, assignee=case.responsible_intern,
        reviewer=case.responsible_lawyer, due_date=datetime.date(2026, 11, 5),
    )  # fmt: skip
    LedgerEntry.objects.create(client=client, case=case, kind="fee", amount=10,
                               date=datetime.date(2026, 11, 1))  # fmt: skip
    url = reverse("clients:delete", args=[client.pk])
    page = admin_client_logged.get(url).content.decode()
    assert "Dosya" in page and "Görev" in page and "Muhasebe hareketi" in page
    admin_client_logged.post(url, {"confirm": "1"})
    assert not Client.objects.filter(pk=client.pk).exists()
    assert not Task.objects.exists() and not LedgerEntry.objects.exists()


def test_contact_rows_prefilled_and_optional(lawyer_client, lawyer, intern):
    r = lawyer_client.get(reverse("clients:create"))
    kinds = [f.initial.get("kind") for f in r.context["formsets"]["iletisim"][0].forms]
    assert kinds == ["phone", "email", "address"]
    # Boş bırakılan iletişim/IBAN/vekalet satırları zorunlu değildir.
    data = {"kind": "person", "first_name": "A", "last_name": "B",
            "responsible_lawyer": lawyer.pk, "responsible_intern": intern.pk,
            **formsets(iban=[{"bank": ""}])}  # fmt: skip
    assert lawyer_client.post(reverse("clients:create"), data).status_code == 302


def test_default_sort_by_poa_number_then_newest(lawyer_client, client_factory):
    old_poa = client_factory(first_name="Eski", poa_no=5)
    new_poa = client_factory(first_name="Yeni", poa_no=121)
    no_poa_old = client_factory(first_name="Vekaletsiz1")
    no_poa_new = client_factory(first_name="Vekaletsiz2")
    r = lawyer_client.get(reverse("clients:list"))
    # En yeni vekalet numarası üstte; numarası olmayanlar sonda, en yeni kayıt önce.
    assert [c.pk for c in r.context["clients"]] == [
        new_poa.pk, old_poa.pk, no_poa_new.pk, no_poa_old.pk
    ]  # fmt: skip
    r = lawyer_client.get(reverse("clients:list"), {"sort": "poa"})
    assert [c.pk for c in r.context["clients"]][:2] == [old_poa.pk, new_poa.pk]


def test_poa_filter_includes_archive_number_and_existing_powers(lawyer_client, client_factory):
    numbered = client_factory(first_name="Numaralı", poa_no=42)
    documented = client_factory(first_name="Belgeli")
    without_poa = client_factory(first_name="Vekaletsiz")
    PowerOfAttorney.objects.create(
        client=documented,
        notary="Örnek noter",
        date=datetime.date(2026, 1, 2),
        journal_no="123",
    )
    url = reverse("clients:list")
    with_poa = lawyer_client.get(url, {"poa": "yes"})
    assert {c.pk for c in with_poa.context["clients"]} == {numbered.pk, documented.pk}
    without = lawyer_client.get(url, {"poa": "no"})
    assert {c.pk for c in without.context["clients"]} == {without_poa.pk}


def test_same_poa_number_can_be_used_by_different_clients(client_factory, lawyer, intern):
    from apps.clients.forms import ClientForm

    first = client_factory(first_name="Örnek", last_name="Kişi", poa_no=42)
    form = ClientForm(
        data={
            "kind": "person",
            "first_name": "Başka",
            "last_name": "Kişi",
            "poa_no": 42,
            "responsible_lawyer": lawyer.pk,
            "responsible_intern": intern.pk,
        }
    )
    assert form.is_valid(), form.errors
    second = form.save()
    assert first.pk != second.pk and Client.objects.filter(poa_no=42).count() == 2
    assert Client.suggest_poa_no() == 43


def test_poa_filter_includes_linked_reference_without_primary_number(
    lawyer_client, client_factory, admin_user
):
    from apps.imports.models import PowerOfAttorneyReview

    linked = client_factory(first_name="İlişkili")
    absent = client_factory(first_name="Vekaletsiz")
    PowerOfAttorneyReview.objects.create(
        source_sha256="a" * 64,
        source_row=2,
        source_reference="V - 007",
        client=linked,
        created_by=admin_user,
    )
    with_poa = lawyer_client.get(reverse("clients:list"), {"poa": "yes"})
    assert {c.pk for c in with_poa.context["clients"]} == {linked.pk}
    assert "V-7" in with_poa.content.decode()
    without_poa = lawyer_client.get(reverse("clients:list"), {"poa": "no"})
    assert {c.pk for c in without_poa.context["clients"]} == {absent.pk}


def test_shared_reference_is_visible_for_each_linked_client(
    lawyer_client, client_factory, admin_user
):
    from apps.imports.models import PowerOfAttorneyReview, PowerOfAttorneyReviewMember

    first = client_factory(first_name="Birinci", poa_no=7)
    second = client_factory(first_name="İkinci")
    review = PowerOfAttorneyReview.objects.create(
        source_sha256="b" * 64,
        source_row=3,
        source_reference="V-007",
        client=first,
        expected_clients=2,
        created_by=admin_user,
    )
    PowerOfAttorneyReviewMember.objects.create(review=review, client=second)
    assert first.poa_labels == ["V-7"]
    assert second.poa_labels == ["V-7"]
    with_poa = lawyer_client.get(reverse("clients:list"), {"poa": "yes"})
    assert {c.pk for c in with_poa.context["clients"]} == {first.pk, second.pk}


def test_intern_supervisor_fills_form_defaults(lawyer, intern):
    from apps.clients.views import intern_by_lawyer

    intern.supervisor = lawyer
    intern.save()
    assert intern_by_lawyer() == {lawyer.pk: intern.pk}


def test_client_cases_tab_filters_and_sorts(lawyer_client, client_factory, case_factory):
    c = client_factory()
    a = case_factory(client=c, subject="Alacak", archive_no="2026/0001")
    b = case_factory(client=c, subject="Boşanma", archive_no="2026/0002", status="closed")
    url = reverse("clients:cases", args=[c.pk])
    pks = lambda r: [k.pk for k in r.context["client_cases"]]  # noqa: E731
    assert pks(lawyer_client.get(url)) == [b.pk, a.pk]  # varsayılan: en yeni önce
    assert pks(lawyer_client.get(url, {"status": "open"})) == [a.pk]
    assert pks(lawyer_client.get(url, {"q": "bosanma"})) == [b.pk]
    assert pks(lawyer_client.get(url, {"sort": "archive_no"})) == [a.pk, b.pk]
