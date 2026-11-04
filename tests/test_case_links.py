import datetime as dt

import pytest
from django.urls import reverse

from apps.accounting.models import EntryKind, LedgerEntry
from apps.cases import flows, services
from apps.cases.models import Case
from tests.test_cases import _case_data

pytestmark = pytest.mark.django_db


def _trio(case_factory, client_factory):
    owner = client_factory()
    return owner, [
        case_factory(client=owner, archive_no=name, case_type=kind, opened_on=dt.date(2026, i, 1))
        for i, (name, kind) in enumerate(
            [("A", "notice"), ("B", "mediation"), ("C", "civil")], start=1
        )
    ]


def test_link_merges_flows_with_order_and_note(case_factory, client_factory, lawyer):
    owner, (a, b, c) = _trio(case_factory, client_factory)
    services.link_cases(a, b, "Ön aşama", lawyer)
    services.link_cases(b, c, "Dava", lawyer)
    for case in (a, b, c):
        case.refresh_from_db()
    assert a.flow_id == b.flow_id == c.flow_id
    members = services.flow_members(a)
    assert [m.archive_no for m in members] == ["A", "B", "C"]
    assert [m.flow_position for m in members] == [1, 2, 3]
    assert b.flow_note == "Ön aşama" and c.flow_note == "Dava"
    assert [m.pk for m in services.flow_members(c)] == [m.pk for m in members]


def test_link_rules(case_factory, client_factory, lawyer):
    owner, (a, b, c) = _trio(case_factory, client_factory)
    other_client_case = case_factory(client=client_factory(first_name="Başka"), archive_no="X")
    with pytest.raises(services.StatusError):
        services.link_cases(a, a, "", lawyer)
    with pytest.raises(services.StatusError):
        services.link_cases(a, other_client_case, "", lawyer)  # ortak müvekkil yok
    services.link_cases(a, b, "", lawyer)
    with pytest.raises(services.StatusError):
        services.link_cases(b, a, "", lawyer)  # zaten bağlı


def test_unlink_and_move(case_factory, client_factory, lawyer):
    owner, (a, b, c) = _trio(case_factory, client_factory)
    services.link_cases(a, b, "", lawyer)
    services.link_cases(b, c, "", lawyer)
    for case in (a, b, c):
        case.refresh_from_db()
    assert services.move_member(c, "up")
    assert [m.archive_no for m in services.flow_members(a)] == ["A", "C", "B"]
    assert not services.move_member(a, "up")  # en üstte taşınamaz
    services.unlink_case(b, lawyer)
    b.refresh_from_db()
    assert b.flow_id is None
    assert [m.archive_no for m in services.flow_members(a)] == ["A", "C"]
    services.unlink_case(c, lawyer)
    a.refresh_from_db()
    assert a.flow_id is None  # tek dosya kalınca grup dağılır
    assert Case.objects.count() == 3  # hiçbir dosya silinmedi


def test_numbers_get_type_suffixes(case_factory):
    civil = case_factory(case_type="civil", authority="Asliye", official_no="2026/151")
    assert civil.display_name == "ASLİYE - 2026/151 Esas"
    cases = {
        "enforcement": "İcra",
        "investigation": "Soruşturma",
        "mediation": "Arabuluculuk",
        "criminal": "Esas",
        "administrative": "Esas",
    }
    for i, (kind, suffix) in enumerate(cases.items()):
        case = case_factory(case_type=kind, authority="X", official_no="2026/9", archive_no=f"S{i}")
        assert case.official_no_display == f"2026/9 {suffix}"
    notice = case_factory(
        case_type="notice", authority="Noter", official_no="2026/9", archive_no="N"
    )
    assert notice.official_no_display == "2026/9"  # ihtarnamede ek yok
    legacy = case_factory(
        case_type="civil", authority="Y", official_no="2026/191 E.", archive_no="L"
    )
    assert legacy.official_no_display == "2026/191 E."  # eski biçim değişmez
    civil.decision_no = "2026/55"
    assert civil.decision_no_display == "2026/55 Karar"


def test_safahat_tab_shows_status_type_and_detail(
    lawyer_client, case_factory, client_factory, lawyer
):
    owner, (a, b, c) = _trio(case_factory, client_factory)
    services.link_cases(a, b, "Aynı olay", lawyer)
    services.close_case(
        b, {"closing_reason": "full_agreement", "closed_on": dt.date(2026, 5, 1)}, lawyer
    )
    html = lawyer_client.get(a.get_absolute_url()).content.decode()
    html = html[html.index('id="t-safahat"') :]
    assert "AÇIK" in html and "KAPALI" in html
    assert "Tam anlaşma" in html and "Aynı olay" in html
    assert "İlgili dosya oluştur" in html and "İlgili dosya bağla" in html
    assert "Güncel esas dosya" not in html


def test_link_add_view_and_permissions(lawyer_client, case_factory, client_factory, lawyer):
    owner, (a, b, c) = _trio(case_factory, client_factory)
    url = reverse("cases:link_add", args=[a.pk])
    assert lawyer_client.get(url, HTTP_HX_REQUEST="true").status_code == 200
    response = lawyer_client.post(url, {"related": b.pk, "note": "Not"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 204 and response["HX-Trigger"] == "flow-saved"
    b.refresh_from_db()
    assert b.flow_id and b.flow_note == "Not"
    # Bağlantıyı koparma: yönetici ve avukatlar yapabilir (lawyer_client avukattır).
    ok = lawyer_client.post(reverse("cases:link_delete", args=[a.pk, b.pk]))
    assert ok.status_code == 302
    b.refresh_from_db()
    assert b.flow_id is None


def test_intern_cannot_cut_link(client, intern, case_factory, client_factory, lawyer):
    owner, (a, b, c) = _trio(case_factory, client_factory)
    services.link_cases(a, b, "", lawyer)
    client.force_login(intern)
    denied = client.post(reverse("cases:link_delete", args=[a.pk, b.pk]))
    assert denied.status_code == 403
    b.refresh_from_db()
    assert b.flow_id is not None


def test_link_needs_shared_client_and_co_clients_count(case_factory, client_factory, lawyer):
    first, second = client_factory(), client_factory(first_name="İkinci")
    one = case_factory(client=first, archive_no="K1")
    other = case_factory(client=second, archive_no="K2")
    with pytest.raises(services.StatusError):
        services.link_cases(one, other, "", lawyer)  # ortak müvekkil yok
    other.co_clients.add(first, through_defaults={"role": "plaintiff"})  # ilk müvekkil de müvekkil
    services.link_cases(one, other, "", lawyer)
    assert one.client_ids() == {first.pk} and other.client_ids() == {first.pk, second.pk}


def test_case_form_saves_co_clients_with_roles_and_lists_show_them(lawyer_client, client_factory):
    first, second = client_factory(), client_factory(first_name="Ek")
    data = _case_data(
        first,
        **{
            "coclients-TOTAL_FORMS": "1",
            "coclients-0-client": second.pk,
            "coclients-0-role": "defendant",
        },
    )
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    case = Case.objects.get()
    link = case.co_client_links.get()
    assert link.client == second and link.role == "defendant" and link.role_label == "Davalı"
    assert "+1 müvekkil" in lawyer_client.get(reverse("cases:list")).content.decode()
    page = lawyer_client.get(second.get_absolute_url())
    assert case in list(page.context["cases"])
    listed = lawyer_client.get(reverse("cases:list"), {"client": second.pk}).context["cases"]
    assert [c.pk for c in listed] == [case.pk]
    # Ek müvekkil, kendi sıfatının yanında (davalı) asıl müvekkil gibi listelenir.
    detail = lawyer_client.get(case.get_absolute_url())
    groups = {g["label"]: [i["name"] for i in g["items"]] for g in detail.context["party_groups"]}
    assert second.name in groups["Davalı tarafı"] and first.name in groups["Davacı tarafı"]


def test_co_client_rules(lawyer_client, client_factory, case_factory):
    first, second = client_factory(), client_factory(first_name="Ek")
    base = {
        "coclients-TOTAL_FORMS": "1",
        "coclients-0-client": first.pk,
        "coclients-0-role": "defendant",
    }
    assert lawyer_client.post(reverse("cases:create"), _case_data(first, **base)).status_code == 200
    base = {"coclients-TOTAL_FORMS": "1", "coclients-0-client": second.pk}  # sıfat yok
    assert lawyer_client.post(reverse("cases:create"), _case_data(first, **base)).status_code == 200
    assert not Case.objects.exists()
    # Muhasebe hareketi olan ek müvekkil çıkarılamaz.
    case = case_factory(client=first)
    case.co_clients.add(second, through_defaults={"role": "defendant"})
    LedgerEntry.objects.create(
        client=second, case=case, kind=EntryKind.FEE, amount=10, date=dt.date(2026, 1, 1)
    )
    data = _case_data(first, archive_no=case.archive_no)
    assert lawyer_client.post(reverse("cases:update", args=[case.pk]), data).status_code == 200
    assert case.co_clients.filter(pk=second.pk).exists()


def test_ledger_entries_stay_with_their_client_but_totals_are_shared(
    admin_client_logged, case_factory, client_factory, lawyer
):
    first, second = client_factory(), client_factory(first_name="Ek")
    a = case_factory(client=first, archive_no="M1")
    b = case_factory(client=first, archive_no="M2")
    b.co_clients.add(second, through_defaults={"role": "plaintiff"})
    LedgerEntry.objects.create(
        client=first, case=a, kind=EntryKind.FEE, amount=1000, date=dt.date(2026, 1, 1)
    )
    LedgerEntry.objects.create(
        client=second, case=b, kind=EntryKind.EXPENSE, amount=300, date=dt.date(2026, 1, 2)
    )
    assert LedgerEntry.objects.get(case=b).client_id == second.pk  # ek müvekkile yazıldı
    services.link_cases(a, b, "", lawyer)
    response = admin_client_logged.get(a.get_absolute_url())
    assert response.context["ledger_balances"]["balance"] == 1300  # ortak toplam
    assert response.context["multi_client"] is True
    assert "Müvekkil" in response.content.decode()
    # Ekstre müvekkile göre ayrıdır: ek müvekkil yalnızca kendi hareketini görür.
    client_page = admin_client_logged.get(second.get_absolute_url())
    assert [r["entry"].amount for r in client_page.context["ledger_rows"]] == [300]


def test_create_related_case_links_to_existing(lawyer_client, case_factory, client_factory):
    owner = client_factory()
    existing = case_factory(client=owner, archive_no="1", case_type="notice")
    page = lawyer_client.get(reverse("cases:create"), {"iliskili": existing.pk})
    assert page.status_code == 200 and page.context["related_case"] == existing
    data = _case_data(owner, archive_no="2", related_case=existing.pk)
    response = lawyer_client.post(reverse("cases:create"), data)
    assert response.status_code == 302
    new = Case.objects.get(archive_no="2")
    existing.refresh_from_db()
    assert new.flow_id and new.flow_id == existing.flow_id


def test_accounting_is_shared_across_linked_cases(
    lawyer_client, admin_user, case_factory, client_factory, lawyer, client
):
    owner, (a, b, c) = _trio(case_factory, client_factory)
    LedgerEntry.objects.create(
        client=owner, case=a, kind=EntryKind.FEE, amount=1000, date=dt.date(2026, 1, 1)
    )
    LedgerEntry.objects.create(
        client=owner, case=b, kind=EntryKind.EXPENSE, amount=250, date=dt.date(2026, 1, 2)
    )
    services.link_cases(a, b, "", lawyer)
    client.force_login(admin_user)
    for case in (a, b):
        response = client.get(case.get_absolute_url())
        rows = response.context["ledger_rows"]
        assert sorted(r["entry"].amount for r in rows) == [250, 1000]
        assert response.context["ledger_balances"]["balance"] == 1250
    assert [
        r["entry"].amount for r in client.get(c.get_absolute_url()).context["ledger_rows"]
    ] == []


def test_lists_cluster_linked_cases_with_marker(
    lawyer_client, case_factory, client_factory, lawyer
):
    owner = client_factory()
    a = case_factory(client=owner, archive_no="A")
    spacer = case_factory(client=owner, archive_no="S")
    b = case_factory(client=owner, archive_no="B")
    services.link_cases(a, b, "", lawyer)
    ordered = flows.cluster(Case.objects.filter(pk__in=[a.pk, spacer.pk, b.pk]).order_by("pk"))
    assert [c.archive_no for c in ordered] == ["A", "B", "S"]
    assert ordered[0].linked_others == 1 and ordered[0].chain_next and not ordered[0].chain_prev
    assert ordered[1].chain_prev and not ordered[1].chain_next
    html = lawyer_client.get(reverse("cases:list")).content.decode()
    assert "+1 dosya bağlı" in html and "bi-link-45deg" in html
    detail = lawyer_client.get(a.get_absolute_url()).content.decode()
    assert "+1 dosya bağlı" in detail


def test_related_case_form_is_prefilled_but_requires_an_empty_archive_location(
    lawyer_client, case_factory, client_factory
):
    from apps.cases.models import ArchiveFolder, CaseParty
    from apps.clients.models import Party

    owner = client_factory()
    ArchiveFolder.objects.create(name="12", kind="legacy", capacity=20)
    existing = case_factory(
        client=owner,
        archive_folder_no="12",
        archive_no="12",
        case_type="civil",
        client_role="plaintiff",
        authority="Asliye",
        official_no="2026/12",
    )
    party = Party.objects.create(kind="person", name="KARŞI TARAF", lawyer="Av. X")
    CaseParty.objects.create(case=existing, party=party, role="defendant")
    page = lawyer_client.get(reverse("cases:create"), {"iliskili": existing.pk})
    form = page.context["form"]
    assert form.initial["client"] == owner
    assert form.initial["client_role"] == "plaintiff"
    assert (form.initial["archive_folder_no"], form.initial["archive_no"]) == ("12", "")
    assert form.initial["responsible_lawyer"] == existing.responsible_lawyer_id
    rows = page.context["party_formset"].initial
    assert rows[0]["name"] == "KARŞI TARAF" and rows[0]["existing_party"] == party.pk
    html = page.content.decode()
    assert (
        existing.display_name in html and "12 / 12 ·" not in html.split("ilgili dosyası")[0][-200:]
    )
    # Bağlı dosyalar da boş bir fiziki yer kullanır.
    data = _case_data(
        owner,
        archive_folder_no="12",
        archive_no="12",
        related_case=existing.pk,
        **{
            "parties-TOTAL_FORMS": "1",
            "parties-INITIAL_FORMS": "1",
            "parties-0-role": "defendant",
            "parties-0-kind": "person",
            "parties-0-name": "KARŞI TARAF",
            "parties-0-existing_party": party.pk,
        },
    )
    response = lawyer_client.post(reverse("cases:create"), data)
    assert response.status_code == 200 and "archive_no" in response.context["form"].errors
    data["archive_no"] = "13"
    assert lawyer_client.post(reverse("cases:create"), data).status_code == 302
    new = Case.objects.exclude(pk=existing.pk).get()
    existing.refresh_from_db()
    assert new.flow_id == existing.flow_id and new.flow_id
    assert new.party_links.get().party_id == party.pk  # aynı taraf kaydı kullanıldı
    assert Party.objects.count() == 1
    # Bağlı olmayan bir dosya için aynı yer hâlâ uyarı verir.
    data = _case_data(owner, archive_folder_no="12", archive_no="12", archive_no_x="1")
    response = lawyer_client.post(reverse("cases:create"), data)
    assert response.status_code == 200 and "archive_no" in response.context["form"].errors
