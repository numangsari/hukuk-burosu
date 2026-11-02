import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.cases import seizure_types
from apps.cases.forms import SeizureForm
from apps.cases.models import CaseCoClient, CaseParty, Seizure
from apps.cases.seizures import create_due_tasks, save_seizure
from apps.clients.models import Party
from apps.reports.definitions import build_client_cases, build_seizures
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def debtor_case(case_factory):
    case = case_factory(case_type="enforcement")
    debtor = Party.objects.create(kind="person", name="Örnek borçlu")
    CaseParty.objects.create(case=case, party=debtor, role="debtor")
    return case, debtor


def payload(borrower, kind="vehicle", state="vehicle_seized", **kwargs):
    data = dict(
        debtor=f"party:{borrower.pk}",
        kind=kind,
        state=state,
        seized_on="2026-01-01",
        employer="Örnek işveren",
        bank_name="Örnek Banka",
        plate="34 ABC 123",
        property_info="Örnek ilçe 1 ada 2 parsel",
        address="Örnek mahalle, 1. sokak",
        notice_stage="89/1",
        related_case_info="Örnek İcra Dairesi 2026/10",
        is_active="on",
    )
    data.update(kwargs)
    return data


def test_multiple_banks_create_individual_records(debtor_case, lawyer_client):
    case, debtor = debtor_case
    response = lawyer_client.post(
        reverse("cases:seizure_add", args=[case.pk]),
        payload(debtor, "bank", "bank_letter", bank_name="Ziraat, Vakıf, İş"),
    )
    assert response.status_code == 302, response.context["form"].errors
    assert list(case.seizures.order_by("pk").values_list("bank_name", flat=True)) == [
        "Ziraat",
        "Vakıf",
        "İş",
    ]
    response = lawyer_client.post(
        reverse("cases:seizure_add", args=[case.pk]),
        payload(debtor, "bank", "bank_letter", bank_name="Banka, , Diğer"),
    )
    assert response.status_code == 200
    assert case.seizures.count() == 3


def test_seizure_delete_is_admin_only(debtor_case, lawyer, lawyer_client, admin_user):
    case, debtor = debtor_case
    form = SeizureForm(payload(debtor), instance=Seizure(case=case))
    assert form.is_valid()
    item = save_seizure(case, form, lawyer)
    url = reverse("cases:seizure_delete", args=[case.pk, item.pk])
    assert lawyer_client.post(url).status_code == 403
    assert case.seizures.count() == 1
    lawyer_client.force_login(admin_user)
    assert lawyer_client.post(url).status_code == 302
    assert not case.seizures.exists()


@pytest.mark.parametrize(
    "kind,state",
    [(kind, state) for kind, states in seizure_types.STATES.items() for state, _ in states],
)
def test_every_requested_type_and_state_is_valid(debtor_case, kind, state):
    case, debtor = debtor_case
    form = SeizureForm(payload(debtor, kind, state), instance=Seizure(case=case))
    assert form.is_valid(), form.errors
    item = form.save(commit=False)
    assert item.debtor_party == debtor and item.debtor == debtor.name
    assert item.kind == kind and item.state_label == dict(seizure_types.STATES[kind])[state]
    if state not in seizure_types.SEIZED_STATES:
        assert item.seized_on is None
    if kind in {"vehicle", "property"} and state in seizure_types.RENEWAL_STATES:
        assert item.renewal_on == dt.date(2026, 12, 2)
    else:
        assert item.renewal_on is None


@pytest.mark.parametrize(
    "kind,state,missing",
    [
        ("bank", "bank_letter", "bank_name"),
        ("vehicle", "vehicle_seized", "plate"),
        ("property", "property_sale", "property_info"),
        ("location", "location_failed", "address"),
        ("notice", "notice_requested", "notice_stage"),
        ("claim", "claim_exists", "related_case_info"),
        ("vehicle", "capture_requested", "seized_on"),
    ],
)
def test_type_details_are_required(debtor_case, kind, state, missing):
    case, debtor = debtor_case
    form = SeizureForm(payload(debtor, kind, state, **{missing: ""}), instance=Seizure(case=case))
    assert not form.is_valid() and missing in form.errors


def test_only_registered_debtors_can_be_selected(debtor_case, case_factory, client_factory):
    case, debtor = debtor_case
    creditor = Party.objects.create(kind="person", name="Örnek alacaklı")
    CaseParty.objects.create(case=case, party=creditor, role="creditor")
    other_case = case_factory(case_type="enforcement")
    other_party = Party.objects.create(kind="person", name="Başka borçlu")
    CaseParty.objects.create(case=other_case, party=other_party, role="debtor")
    extra = client_factory(first_name="Ek", last_name="Borçlu")
    CaseCoClient.objects.create(case=case, client=extra, role="debtor")
    case.client_role = "debtor"
    case.save()
    form = SeizureForm(instance=Seizure(case=case))
    choices = dict(form.fields["debtor"].choices)
    assert f"party:{debtor.pk}" in choices and f"client:{extra.pk}" in choices
    assert f"client:{case.client_id}" in choices
    assert f"party:{creditor.pk}" not in choices and f"party:{other_party.pk}" not in choices
    for bad in [f"party:{creditor.pk}", f"party:{other_party.pk}", "Serbest isim"]:
        form = SeizureForm(payload(debtor, debtor=bad), instance=Seizure(case=case))
        assert not form.is_valid() and "debtor" in form.errors
    form = SeizureForm(payload(debtor, debtor=f"client:{extra.pk}"), instance=Seizure(case=case))
    assert form.is_valid(), form.errors
    assert form.instance.debtor_client == extra and form.instance.debtor_party is None


def test_borrower_is_checked_again_before_save(debtor_case, lawyer):
    case, debtor = debtor_case
    form = SeizureForm(payload(debtor), instance=Seizure(case=case))
    assert form.is_valid()
    CaseParty.objects.filter(case=case, party=debtor).update(role="creditor")
    with pytest.raises(ValidationError):
        save_seizure(case, form, lawyer)
    assert not Seizure.objects.exists()


@pytest.mark.parametrize(
    "kind,state,field,value",
    [
        ("bank", "bank_letter", "bank_name", "A Bankası; B Bankası"),
        ("vehicle", "vehicle_seized", "plate", "34 ABC 123 / 06 XYZ 456"),
        ("vehicle", "vehicle_seized", "plate", "34ABC123 06XYZ456"),
    ],
)
def test_multiple_banks_or_plates_cannot_be_combined(debtor_case, kind, state, field, value):
    case, debtor = debtor_case
    form = SeizureForm(payload(debtor, kind, state, **{field: value}), instance=Seizure(case=case))
    assert not form.is_valid() and field in form.errors


def test_annual_suggestion_handles_leap_day_and_keeps_manual_override(debtor_case):
    case, debtor = debtor_case
    assert seizure_types.suggested_renewal(dt.date(2024, 2, 29)) == dt.date(2025, 1, 29)
    form = SeizureForm(payload(debtor, renewal_on="2026-11-15"), instance=Seizure(case=case))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["renewal_on"] == dt.date(2026, 11, 15)
    form = SeizureForm(payload(debtor, "claim", "claim_exists"), instance=Seizure(case=case))
    assert form.is_valid() and form.cleaned_data["renewal_on"] is None


def test_typed_renewal_generates_one_task_with_plate(debtor_case, lawyer):
    case, debtor = debtor_case
    form = SeizureForm(payload(debtor), instance=Seizure(case=case))
    assert form.is_valid(), form.errors
    item = save_seizure(case, form, lawyer)
    assert create_due_tasks(dt.date(2026, 12, 1)) == (0, 0)
    assert create_due_tasks(dt.date(2026, 12, 2)) == (1, 0)
    task = Task.objects.get(case=case)
    assert "34 ABC 123" in task.title and "Araç Haczi" in task.notes
    assert task.due_date == item.renewal_on
    assert create_due_tasks(dt.date(2026, 12, 3)) == (0, 0)


def test_negative_seizure_states_do_not_count_as_existing_seizures(debtor_case, lawyer):
    case, debtor = debtor_case
    form = SeizureForm(payload(debtor, "vehicle", "vehicle_none"), instance=Seizure(case=case))
    assert form.is_valid(), form.errors
    save_seizure(case, form, lawyer)
    assert create_due_tasks(dt.date(2027, 1, 1)) == (0, 0)
    result = build_client_cases({}, lawyer)
    row = dict(zip([column.label for column in result.columns], result.rows[0], strict=True))
    assert row["Aktif haciz"] == 0 and row["Yenileme tarihi"] is None
    result = build_seizures({}, lawyer)
    assert result.rows[0][-1] == "Araç Yok"


def test_controller_keeps_banks_and_plates_as_separate_rows(debtor_case, lawyer_client):
    case, debtor = debtor_case
    url = reverse("cases:seizure_add", args=[case.pk])
    for bank in ["Örnek Bir Bankası", "Örnek İki Bankası"]:
        response = lawyer_client.post(url, payload(debtor, "bank", "bank_letter", bank_name=bank))
        assert response.status_code == 302
    for plate in ["34 ABC 123", "06 XYZ 456"]:
        response = lawyer_client.post(url, payload(debtor, plate=plate))
        assert response.status_code == 302
    assert case.seizures.count() == 4
    html = lawyer_client.get(case.get_absolute_url()).content.decode()
    assert "Örnek Bir Bankası" in html and "34 ABC 123" in html


def test_notice_updates_stage_on_the_same_record(debtor_case, lawyer_client):
    case, debtor = debtor_case
    response = lawyer_client.post(
        reverse("cases:seizure_add", args=[case.pk]), payload(debtor, "notice", "notice_requested")
    )
    assert response.status_code == 302
    item = case.seizures.get()
    response = lawyer_client.post(
        reverse("cases:seizure_edit", args=[case.pk, item.pk]),
        payload(debtor, "notice", "notice_objected", notice_stage="89/2"),
    )
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.notice_stage == "89/2" and item.state == "notice_objected"
    assert case.seizures.count() == 1 and item.renewal_on is None


def test_case_type_is_immediately_left_of_status_in_both_lists(lawyer_client, case_factory):
    case = case_factory()
    for url in [reverse("cases:list"), reverse("clients:cases", args=[case.client_id])]:
        html = lawyer_client.get(url).content.decode()
        assert html.index("Dosya türü</") < html.index("Durum</")
