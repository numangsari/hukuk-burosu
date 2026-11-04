import pytest
from django.urls import reverse

from apps.cases.models import ArchiveFolder, Case
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db


def test_folder_creation_defaults_and_custom_capacity(lawyer_client):
    office = OfficeSettings.load()
    assert office.archive_folder_default_capacity == 8
    office.archive_folder_default_capacity = 12
    office.save()
    url = reverse("archive:create") + "?pencere=1"
    response = lawyer_client.get(url)
    assert response.status_code == 200
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert response.context["form"]["capacity"].value() == 12
    response = lawyer_client.post(url, {"kind": "open", "name": "12", "capacity": 8})
    assert "window.parent.location.reload()" in response.content.decode()
    folder = ArchiveFolder.objects.get(name="Açık 12")
    assert folder.capacity == 8 and folder.kind == "open"
    response = lawyer_client.get(reverse("archive:list"), {"view": "explorer"})
    assert "Açık 12" in response.content.decode()
    assert (
        lawyer_client.post(url, {"kind": "open", "name": "12", "capacity": 8})
        .context["form"]
        .errors
    )


def test_default_capacity_in_office_form():
    from apps.office.forms import OfficeForm

    office = OfficeSettings.load()
    data = {
        "name": office.name,
        "idle_minutes": office.idle_minutes,
        "notice_default_due_days": office.notice_default_due_days,
        "archive_folder_default_capacity": "15",
    }
    form = OfficeForm(data, instance=office)
    assert form.is_valid(), form.errors
    form.save()
    office.refresh_from_db()
    assert office.archive_folder_default_capacity == 15
    data["archive_folder_default_capacity"] = "0"
    form = OfficeForm(data, instance=office)
    assert not form.is_valid()


@pytest.mark.parametrize(
    ("kind", "custom_kind", "expected"),
    [
        ("proxy", "", "Vekaletnameler 1"),
        ("notice", "", "İhtarnameler 1"),
        ("mediation", "", "Arabuluculuklar 1"),
        ("contract", "", "Sözleşmeler 1"),
        ("fee_contract", "", "Avukatlık Ücret Sözleşmeleri 1"),
        ("other", "Özel belgeler", "Özel belgeler 1"),
    ],
)
def test_folder_types(lawyer_client, kind, custom_kind, expected):
    response = lawyer_client.post(
        reverse("archive:create"),
        {"kind": kind, "custom_kind": custom_kind, "name": "1", "capacity": 8},
    )
    assert response.status_code == 302
    assert ArchiveFolder.objects.filter(name=expected, kind=kind, custom_kind=custom_kind).exists()


def test_other_folder_type_requires_name(lawyer_client):
    response = lawyer_client.post(
        reverse("archive:create"), {"kind": "other", "name": "1", "capacity": 8}
    )
    assert "custom_kind" in response.context["form"].errors


def test_managed_folder_slots_enforce_capacity_and_uniqueness(lawyer_client, case_factory):
    folder = ArchiveFolder.objects.create(name="Açık 12", kind="open", capacity=8)
    existing = case_factory(archive_folder_no=folder.name, archive_no="1")
    case = case_factory(archive_folder_no="", archive_no="")
    url = reverse("archive:update_location", args=[case.pk])
    for number in ("0", "9", "01", "abc"):
        response = lawyer_client.post(url, {"archive_folder_no": folder.name, "archive_no": number})
        assert "alert-danger" in response.content.decode()
        case.refresh_from_db()
        assert case.archive_folder_no == ""
    response = lawyer_client.post(url, {"archive_folder_no": folder.name, "archive_no": "02"})
    assert response.status_code == 302
    case.refresh_from_db()
    assert case.archive_folder_no == folder.name and case.archive_no == "2"
    existing.refresh_from_db()
    assert existing.archive_no == "1"


def test_legacy_capacity_can_be_set_without_overwriting_cases(lawyer_client, case_factory):
    folder = ArchiveFolder.objects.create(name="Eski klasör", kind="legacy")
    case = case_factory(archive_folder_no=folder.name, archive_no="10")
    url = reverse("archive:folder_detail", args=[folder.name])
    lawyer_client.post(url, {"capacity": "8"})
    folder.refresh_from_db()
    assert folder.capacity is None
    lawyer_client.post(url, {"capacity": "12"})
    folder.refresh_from_db()
    case.refresh_from_db()
    assert folder.capacity == 12 and case.archive_no == "10"


def test_legacy_capacity_backfill_preserves_existing_numbers(case_factory):
    from importlib import import_module

    from django.apps import apps

    folder = ArchiveFolder.objects.create(name="Eski kapasite", kind="legacy")
    for number in ("1", "1", "Eski", "12"):
        case_factory(archive_folder_no=folder.name, archive_no=number)
    module = import_module("apps.cases.migrations.0038_legacy_folder_capacities")
    module.set_legacy_capacities(apps, None)
    folder.refresh_from_db()
    assert folder.capacity == 12
    assert sorted(
        Case.objects.filter(archive_folder_no=folder.name).values_list("archive_no", flat=True)
    ) == ["1", "1", "12", "Eski"]


def test_case_creation_requires_registered_folder(lawyer_client, client_factory):
    from .test_cases import _case_data

    client = client_factory()
    data = _case_data(client)
    data["archive_folder_no"] = "Kayıtsız klasör"
    response = lawyer_client.post(reverse("cases:create"), data)
    assert "archive_folder_no" in response.context["form"].errors


def test_available_slots_exclude_occupied_and_preserve_current(lawyer_client, case_factory):
    folder = ArchiveFolder.objects.create(name="Açık 7", kind="open", capacity=4)
    current = case_factory(archive_folder_no=folder.name, archive_no="2")
    case_factory(archive_folder_no=folder.name, archive_no="4")
    url = reverse("archive:available_slots")
    response = lawyer_client.get(url, {"folder": folder.name})
    assert response.json()["slots"] == ["1", "3"]
    response = lawyer_client.get(url, {"folder": folder.name, "case": current.pk})
    assert response.json()["slots"] == ["1", "2", "3"]
    form = lawyer_client.get(reverse("cases:update", args=[current.pk])).context["form"]
    assert form["archive_folder_no"].field.widget.input_type == "select"
    assert form["archive_no"].field.widget.input_type == "select"
    assert form["archive_no"].value() == "2"


def test_unknown_capacity_blocks_new_assignment_but_keeps_existing(lawyer_client, case_factory):
    folder = ArchiveFolder.objects.create(name="Eski 1", kind="legacy")
    existing = case_factory(archive_folder_no=folder.name, archive_no="Eski numara")
    response = lawyer_client.get(reverse("archive:available_slots"), {"folder": folder.name})
    assert response.json() == {"slots": [], "capacity_missing": True}
    response = lawyer_client.get(
        reverse("archive:available_slots"), {"folder": folder.name, "case": existing.pk}
    )
    assert response.json()["slots"] == ["Eski numara"]


def test_slots_respect_occupied_places_even_when_case_is_hidden(
    lawyer_client, admin_user, client_factory, case_factory
):
    office = OfficeSettings.load()
    office.case_visibility_mode = OfficeSettings.CaseVisibilityMode.RESTRICTED
    office.save()
    client = client_factory(responsible_lawyer=admin_user, responsible_intern=None)
    folder = ArchiveFolder.objects.create(name="Açık gizli", kind="open", capacity=2)
    hidden = case_factory(client=client, archive_folder_no=folder.name, archive_no="1")
    url = reverse("archive:available_slots")
    assert lawyer_client.get(url, {"folder": folder.name}).json()["slots"] == ["2"]
    assert lawyer_client.get(url, {"folder": folder.name, "case": hidden.pk}).status_code == 404


def test_legacy_duplicate_and_non_numeric_locations_remain_unchanged(lawyer_client, case_factory):
    from .test_cases import _case_data

    folder = ArchiveFolder.objects.create(name="Eski 2", kind="legacy", capacity=8)
    first = case_factory(archive_folder_no=folder.name, archive_no="1")
    case_factory(archive_folder_no=folder.name, archive_no="1")
    third = case_factory(archive_folder_no=folder.name, archive_no="A")
    for case in (first, third):
        response = lawyer_client.post(
            reverse("archive:update_location", args=[case.pk]),
            {"archive_folder_no": folder.name, "archive_no": case.archive_no},
        )
        assert response.status_code == 302
        data = _case_data(case.client, archive_folder_no=folder.name, archive_no=case.archive_no)
        assert lawyer_client.post(reverse("cases:update", args=[case.pk]), data).status_code == 302
    response = lawyer_client.get(reverse("archive:folder_detail", args=[folder.name]))
    assert response.context["needs_review"]


def test_new_case_respects_folder_capacity(lawyer_client, client_factory, case_factory):
    from .test_cases import _case_data

    folder = ArchiveFolder.objects.create(name="Açık 5", kind="open", capacity=8)
    case_factory(archive_folder_no=folder.name, archive_no="1")
    client = client_factory()
    url = reverse("cases:create")
    for number in ("9", "01"):
        response = lawyer_client.post(
            url, _case_data(client, archive_folder_no=folder.name, archive_no=number)
        )
        assert "archive_no" in response.context["form"].errors
    response = lawyer_client.post(
        url, _case_data(client, archive_folder_no=folder.name, archive_no="2")
    )
    assert response.status_code == 302
