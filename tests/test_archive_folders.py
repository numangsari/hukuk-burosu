import pytest
from django.urls import reverse

from apps.cases.models import ArchiveCategory, ArchiveFolder, Case
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db


def test_folder_creation_defaults_and_custom_capacity(lawyer_client):
    office = OfficeSettings.load()
    assert office.archive_folder_default_capacity == 8
    office.archive_folder_default_capacity = 12
    office.save()
    category, _ = ArchiveCategory.objects.get_or_create(name="Dava", tracks_state=True)
    url = reverse("archive:create") + "?pencere=1"
    response = lawyer_client.get(url)
    assert response.status_code == 200
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert response.context["form"]["capacity"].value() == 12
    response = lawyer_client.post(
        url, {"category": category.pk, "physical_state": "open", "capacity": 8}
    )
    assert "window.parent.location.reload()" in response.content.decode()
    folder = ArchiveFolder.objects.filter(category=category, physical_state="open").first()
    assert folder and folder.capacity == 8
    response = lawyer_client.get(reverse("archive:list"), {"view": "explorer"})
    assert folder.name in response.content.decode()


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


def test_category_creation_and_initial_folders(lawyer_client):
    url = reverse("archive:category_create")
    response = lawyer_client.post(
        url,
        {"name": "Özel Danışmanlık", "capacity": 10, "tracks_state": "on"},
    )
    assert response.status_code == 302
    category = ArchiveCategory.objects.get(name="Özel Danışmanlık")
    assert category.tracks_state is True
    assert ArchiveFolder.objects.filter(
        name="Açık Özel Danışmanlık 1", category=category, capacity=10
    ).exists()
    assert ArchiveFolder.objects.filter(
        name="Kapalı Özel Danışmanlık 1", category=category, capacity=10
    ).exists()


def test_category_creation_single_state(lawyer_client):
    url = reverse("archive:category_create")
    response = lawyer_client.post(
        url,
        {"name": "Arşiv Ayrımsız", "capacity": 5, "tracks_state": ""},
    )
    assert response.status_code == 302
    category = ArchiveCategory.objects.get(name="Arşiv Ayrımsız")
    assert category.tracks_state is False
    assert ArchiveFolder.objects.filter(
        name="Arşiv Ayrımsız 1", category=category, physical_state="single", capacity=5
    ).exists()
    assert not ArchiveFolder.objects.filter(name__startswith="Açık Arşiv Ayrımsız").exists()


def test_next_number_endpoint(lawyer_client):
    category, _ = ArchiveCategory.objects.get_or_create(name="Test Türü", tracks_state=True)
    url = reverse("archive:next_number")
    response = lawyer_client.get(url, {"category": category.pk, "state": "open"})
    assert response.status_code == 200
    assert response.json()["number"] == 1
    ArchiveFolder.objects.create(
        name="Açık Test Türü 1",
        kind=ArchiveFolder.Kind.CATEGORY,
        category=category,
        physical_state="open",
        number=1,
        capacity=8,
    )
    response = lawyer_client.get(url, {"category": category.pk, "state": "open"})
    assert response.json()["number"] == 2


def test_client_specific_archive(lawyer):
    from apps.cases.archive_categories import sync_client_archive
    from apps.clients.models import Client

    client = Client.objects.create(
        kind="person",
        first_name="Özel",
        last_name="Müvekkil",
        physical_archive_enabled=True,
        responsible_lawyer=lawyer,
    )
    sync_client_archive(client, True, True, lawyer)
    category = ArchiveCategory.objects.get(client=client)
    assert category.name == "ÖZEL MÜVEKKİL"
    assert ArchiveFolder.objects.filter(category=category, physical_state="open").exists()
    assert ArchiveFolder.objects.filter(category=category, physical_state="closed").exists()


def test_close_and_reopen_with_archive_placement(lawyer_client, case_factory):
    category, _ = ArchiveCategory.objects.get_or_create(name="Dava", tracks_state=True)
    open_folder, _ = ArchiveFolder.objects.get_or_create(
        name="Açık Dava 1",
        defaults={"category": category, "physical_state": "open", "number": 1, "capacity": 8},
    )
    closed_folder, _ = ArchiveFolder.objects.get_or_create(
        name="Kapalı Dava 1",
        defaults={"category": category, "physical_state": "closed", "number": 1, "capacity": 8},
    )
    case = case_factory(case_type="civil", archive_folder_no=open_folder.name, archive_no="1")
    # Kapatırken kapalı arşive yerleştir
    close_url = reverse("cases:close", args=[case.pk])
    response = lawyer_client.post(
        close_url,
        {
            "closing_reason": "waiver",
            "closed_on": "2026-11-01",
            "archive_folder_no": closed_folder.name,
            "archive_no": "1",
        },
    )
    assert response.status_code == 302
    case.refresh_from_db()
    assert case.status == "closed"
    assert case.archive_folder_no == closed_folder.name
    assert case.archive_no == "1"
    assert case.archive_needs_review is False

    # Arşiv seçmeden kapatma durumu: archive_needs_review = True olmalı
    case2 = case_factory(case_type="civil", archive_folder_no=open_folder.name, archive_no="2")
    lawyer_client.post(
        reverse("cases:close", args=[case2.pk]),
        {"closing_reason": "waiver", "closed_on": "2026-11-01"},
    )
    case2.refresh_from_db()
    assert case2.status == "closed"
    assert case2.archive_needs_review is True


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
    office.role_permissions = {"cases.view_all": ["admin", "senior", "secretary", "accountant"]}
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


def test_case_archive_folder_sync_and_update_fields(client_factory, case_factory):
    client = client_factory()
    folder1 = ArchiveFolder.objects.create(name="Açık Test 1", kind="open", capacity=10)
    folder2 = ArchiveFolder.objects.create(name="Açık Test 2", kind="open", capacity=10)

    # 1. Yeni kayıt - archive_folder_no ile oluşturma
    case = case_factory(client=client, archive_folder_no=folder1.name, archive_no="1")
    assert case.archive_folder == folder1
    assert case.archive_folder_no == folder1.name

    # 2. archive_folder FK doğrudan atandığında senkronizasyon
    case.archive_folder = folder2
    case.save()
    case.refresh_from_db()
    assert case.archive_folder == folder2
    assert case.archive_folder_no == folder2.name

    # 3. update_fields ile save yapıldığında da senkronizasyon
    case.archive_folder_no = folder1.name
    case.save(update_fields=["archive_folder_no"])
    case.refresh_from_db()
    assert case.archive_folder == folder1
    assert case.archive_folder_no == folder1.name


def test_client_specific_category_enables_physical_archive(lawyer_client, client_factory):
    client = client_factory(physical_archive_enabled=False)
    url = reverse("archive:category_create")
    data = {
        "name": "Özel Müvekkil Arşivi",
        "capacity": 10,
        "tracks_state": True,
        "is_client_specific": True,
        "client": client.pk,
    }
    response = lawyer_client.post(url, data)
    assert response.status_code == 302
    client.refresh_from_db()
    assert client.physical_archive_enabled is True
    cat = ArchiveCategory.objects.get(name="Özel Müvekkil Arşivi")
    assert cat.client == client


def test_natural_sorting_in_folder_options(lawyer_client, client_factory):
    from apps.cases.archive_categories import natural_sort_key

    folders = ["Dava 10", "Dava 1", "Dava 2", "Dava 20", "Dava 3"]
    sorted_folders = sorted(folders, key=natural_sort_key)
    assert sorted_folders == ["Dava 1", "Dava 2", "Dava 3", "Dava 10", "Dava 20"]

    client = client_factory()
    for name in folders:
        ArchiveFolder.objects.get_or_create(name=name, defaults={"capacity": 10})

    url = reverse("archive:available_folders")
    res = lawyer_client.get(url, {"client": client.pk}).json()
    filtered = [f for f in res["folders"] if f in folders]
    assert filtered == ["Dava 1", "Dava 2", "Dava 3", "Dava 10", "Dava 20"]
