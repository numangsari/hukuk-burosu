import datetime as dt
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.cases.models import Hearing, HearingKind
from apps.office.models import HEARING_TASK_TYPE_NAME, OfficeSettings, TaskType
from apps.tasks.models import Task, TaskStatus

pytestmark = pytest.mark.django_db


def hearing_task_type():
    return TaskType.objects.get_or_create(
        name=HEARING_TASK_TYPE_NAME, defaults={"requires_document": False, "points": 2}
    )[0]


def test_hearing_type_is_hidden_from_general_task_form_and_settings(lawyer_client, admin_user):
    from django.test import Client
    from django.urls import reverse

    from apps.tasks.forms import TaskForm

    task_type = hearing_task_type()
    assert not TaskForm().fields["task_type"].queryset.filter(pk=task_type.pk).exists()
    response = lawyer_client.get(reverse("tasks:list"))
    assert task_type not in response.context["types"]
    client = Client()
    client.force_login(admin_user)
    response = client.get(reverse("accounts:settings"), {"bolum": "gorev_turleri"})
    assert task_type not in response.context["forms"]["gorev_turleri"].queryset


def test_hearing_linked_task_awards_its_task_type_points(case_factory):
    from apps.tasks.services import award_closed_task_points

    office = OfficeSettings.load()
    office.use_task_points = True
    office.save(update_fields=["use_task_points"])
    case = case_factory()
    hearing = Hearing.objects.create(case=case, starts_at=timezone.now())
    task_type = TaskType.objects.create(name="Örnek görev türü", points=10)
    task = Task.objects.create(
        task_type=task_type,
        title="Örnek",
        case=case,
        hearing=hearing,
        assignee=case.responsible_lawyer,
        due_date=timezone.localdate(),
        status=TaskStatus.DONE,
        completed_at=timezone.now(),
    )
    award_closed_task_points(task)
    assert list(task.points_awarded.values_list("points", flat=True)) == [10]


def test_google_sync_disabled_by_default(case_factory):
    from apps.agenda.google_sync import sync_hearing_to_google

    case = case_factory()
    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(days=2),
    )
    # API kapalıyken None döner, hata atmaz
    event_id = sync_hearing_to_google(hearing)
    assert event_id is None
    assert hearing.google_event_id == ""


def test_google_sync_creates_and_patches_event(case_factory, monkeypatch):
    from apps.agenda import google_sync

    office = OfficeSettings.load()
    office.google_calendar_api_enabled = True
    office.google_calendar_id = "test-cal@group.calendar.google.com"
    office.google_service_account_json = '{"project_id": "test"}'
    office.save()

    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_service.events.return_value = mock_events

    # insert dönüşü
    mock_insert_exec = MagicMock(return_value={"id": "google-ev-123"})
    mock_events.insert.return_value.execute = mock_insert_exec

    # patch dönüşü
    mock_patch_exec = MagicMock(return_value={"id": "google-ev-123"})
    mock_events.patch.return_value.execute = mock_patch_exec

    monkeypatch.setattr(
        google_sync, "get_calendar_service", lambda: (mock_service, office.google_calendar_id)
    )

    case = case_factory()
    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(days=2),
    )

    # 1. İlk eşitleme: insert çağrılmalı ve google_event_id kaydedilmeli
    res_id = google_sync.sync_hearing_to_google(hearing)
    assert res_id == "google-ev-123"
    hearing.refresh_from_db()
    assert hearing.google_event_id == "google-ev-123"
    assert mock_events.insert.called

    # 2. İkinci eşitleme: patch çağrılmalı, yeni insert yapılmamalı (mükerrer kayıt engeli)
    mock_events.insert.reset_mock()
    hearing.authority = "Yeni Mahkeme"
    hearing.save()

    res_id2 = google_sync.sync_hearing_to_google(hearing)
    assert res_id2 == "google-ev-123"
    assert not mock_events.insert.called
    assert mock_events.patch.called


def test_hearing_to_google_payload_custom_format_and_color(case_factory):
    from apps.agenda.google_sync import hearing_to_google_payload

    office = OfficeSettings.load()
    office.google_color_hearing = "9"
    office.google_color_discovery = "2"
    office.save()

    case = case_factory()
    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(days=2),
        assigned_to=case.responsible_lawyer,
    )
    payload = hearing_to_google_payload(hearing)
    assert payload["colorId"] == "9"
    assert "location" not in payload
    # Duruşmada önek olmaz, sorumlu sadece ilk adıyla ve köşeli parantezsiz yazılır
    resp_name = case.responsible_lawyer.first_name or case.responsible_lawyer.username
    assert payload["summary"].startswith(f"{resp_name} - ")
    assert case.client.name in payload["summary"]

    # Mazeret durumu: Mazeret de parantezsiz yazılır
    hearing.excuse_submitted = True
    payload_excuse = hearing_to_google_payload(hearing)
    assert payload_excuse["summary"].startswith("Mazeret - ")

    # Keşif durumu: [Keşif] öneki ve keşif rengi
    discovery = Hearing.objects.create(
        case=case,
        kind=HearingKind.DISCOVERY,
        starts_at=timezone.now() + dt.timedelta(days=3),
        assigned_to=case.responsible_lawyer,
    )
    payload_disc = hearing_to_google_payload(discovery)
    assert payload_disc["colorId"] == "2"
    assert payload_disc["summary"].startswith(f"[Keşif] {resp_name} - ")


def test_hearing_events_show_information_regardless_of_connected_task(case_factory):

    from apps.agenda.services import hearing_events

    case = case_factory()
    now = timezone.now()
    Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=now + dt.timedelta(days=1),
    )
    h_with_task = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=now + dt.timedelta(days=2),
    )
    task_type = hearing_task_type()
    Task.objects.create(
        task_type=task_type,
        title="DURUŞMA İŞLEMLERİ",
        case=case,
        client=case.client,
        assignee=case.responsible_lawyer,
        due_date=(now + dt.timedelta(days=2)).date(),
        hearing=h_with_task,
    )

    events = hearing_events(now.date(), (now + dt.timedelta(days=5)).date())

    assert len(events) == 2
    assert all(
        event.url == f"/durusmalar/{h.pk}/" and event.client_name
        for event, h in zip(events, Hearing.objects.order_by("starts_at"), strict=True)
    )


def test_google_payload_omits_notes_and_result(case_factory):
    from apps.agenda.google_sync import hearing_to_google_payload

    hearing = Hearing.objects.create(
        case=case_factory(),
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(days=2),
        notes="Gizli iç not",
        result="Gizli ara karar",
    )
    description = hearing_to_google_payload(hearing)["description"]
    assert "Gizli iç not" not in description
    assert "Gizli ara karar" not in description
