import datetime as dt
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.cases.hearing_tasks import create_due_hearing_tasks
from apps.cases.models import CaseEvent, Hearing, HearingKind, HearingStatus
from apps.office.models import OfficeSettings, TaskType
from apps.tasks import services
from apps.tasks.models import Task, TaskStatus

pytestmark = pytest.mark.django_db


def test_hearing_type_is_hidden_from_general_task_form_and_settings(lawyer_client, admin_user):
    from django.test import Client
    from django.urls import reverse

    from apps.cases.hearing_tasks import get_or_create_hearing_task_type
    from apps.tasks.forms import TaskForm

    task_type = get_or_create_hearing_task_type()
    assert not TaskForm().fields["task_type"].queryset.filter(pk=task_type.pk).exists()
    response = lawyer_client.get(reverse("tasks:list"))
    assert task_type not in response.context["types"]
    client = Client()
    client.force_login(admin_user)
    response = client.get(reverse("accounts:settings"), {"bolum": "gorev_turleri"})
    assert task_type not in response.context["forms"]["gorev_turleri"].queryset


def test_hearing_task_awards_two_points_even_if_type_has_other_points(case_factory):
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
    assert list(task.points_awarded.values_list("points", flat=True)) == [2]


def test_create_due_hearing_tasks_one_day_before(case_factory):
    case = case_factory()
    now = timezone.now()
    tomorrow_morning = now + dt.timedelta(days=1)

    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=tomorrow_morning,
        authority="İstanbul 1. Asliye Hukuk Mahkemesi",
        room="12",
    )

    created_tasks = create_due_hearing_tasks(reference_date=now.date())
    assert len(created_tasks) == 1
    task = created_tasks[0]

    assert task.hearing == hearing
    assert task.case == case
    assert task.client == case.client
    assert task.assignee == case.responsible_lawyer
    assert task.reviewer is None
    assert "DURUŞMASI İŞLEMLERİ YAPILACAK VE MÜVEKKİLE BİLGİ VERİLECEK" in task.title

    # İkinci kez çağrıldığında mükerrer üretilmemeli
    again = create_due_hearing_tasks(reference_date=now.date())
    assert len(again) == 0


def test_close_hearing_task_with_excuse(case_factory):
    case = case_factory()
    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(hours=2),
    )
    task_type = TaskType.objects.first()
    task = Task.objects.create(
        case=case,
        title="Duruşma görevi",
        due_date=timezone.localdate(),
        task_type=task_type,
        assignee=case.responsible_lawyer,
        reviewer=None,
        hearing=hearing,
    )

    services.perform(
        task=task,
        key="close",
        user=case.responsible_lawyer,
        comment="Mesleki mazeret sunuldu.",
        hearing_outcome="excused",
    )

    task.refresh_from_db()
    hearing.refresh_from_db()

    assert task.status == TaskStatus.DONE
    assert task.hearing_outcome == "excused"
    assert hearing.excuse_submitted is True
    assert hearing.status == HearingStatus.POSTPONED
    assert "Mesleki mazeret sunuldu." in hearing.notes

    event = CaseEvent.objects.filter(case=case, kind=CaseEvent.Kind.HEARING).first()
    assert event is not None
    assert "Mazeret" in event.title


@pytest.mark.parametrize("existing", [False, True])
def test_close_hearing_task_creates_or_reuses_next_hearing(case_factory, existing):
    case = case_factory()
    hearing = Hearing.objects.create(case=case, starts_at=timezone.now(), authority="Mahkeme")
    task = Task.objects.create(
        case=case,
        client=case.client,
        title="Duruşma",
        due_date=timezone.localdate(),
        task_type=TaskType.objects.first(),
        assignee=case.responsible_lawyer,
        hearing=hearing,
    )
    next_start = (timezone.localtime(timezone.now()) + dt.timedelta(days=30)).replace(
        second=0, microsecond=0
    )
    if existing:
        Hearing.objects.create(case=case, starts_at=next_start)
    services.perform(
        task,
        "close",
        case.responsible_lawyer,
        comment="Mazeret sunuldu.",
        hearing_outcome="excused",
        next_hearing_at=next_start.strftime("%Y-%m-%dT%H:%M"),
    )
    assert Hearing.objects.filter(case=case, starts_at=next_start).count() == 1
    if not existing:
        from apps.imports.portal_case_sync import sync_record_hearings

        record = MagicMock()
        record.data = {
            "durusmalar": [{"kayitId": "123", "tarihSaat": next_start.strftime("%Y-%m-%d %H:%M")}]
        }
        sync_record_hearings(case, record)
        assert Hearing.objects.filter(case=case, starts_at=next_start).count() == 1
        assert Hearing.objects.get(case=case, starts_at=next_start).portal_ref == "123"


def test_invalid_next_hearing_does_not_close_task(case_factory):
    case = case_factory()
    hearing = Hearing.objects.create(case=case, starts_at=timezone.now())
    task = Task.objects.create(
        case=case,
        title="Duruşma",
        due_date=timezone.localdate(),
        task_type=TaskType.objects.first(),
        assignee=case.responsible_lawyer,
        hearing=hearing,
    )
    with pytest.raises(ValidationError, match="geçerli tarih"):
        services.perform(
            task,
            "close",
            case.responsible_lawyer,
            hearing_outcome="excused",
            next_hearing_at="geçersiz",
        )
    task.refresh_from_db()
    assert task.status == TaskStatus.ACTIVE


def test_hearing_task_does_not_require_petition(case_factory):
    case = case_factory()
    hearing = Hearing.objects.create(case=case, starts_at=timezone.now())
    task_type = TaskType.objects.create(name="Duruşma için belge testi", requires_document=True)
    task = Task.objects.create(
        case=case,
        title="Duruşma",
        due_date=timezone.localdate(),
        task_type=task_type,
        assignee=case.responsible_lawyer,
        hearing=hearing,
    )
    services.perform(task, "close", case.responsible_lawyer, hearing_outcome="excused")
    assert task.status == TaskStatus.DONE


def test_hearing_task_detail_highlights_excuse_and_note(lawyer_client, case_factory):
    case = case_factory()
    hearing = Hearing.objects.create(case=case, starts_at=timezone.now(), excuse_submitted=True)
    task = Task.objects.create(
        case=case,
        client=case.client,
        title="Duruşma",
        due_date=timezone.localdate(),
        task_type=TaskType.objects.first(),
        assignee=case.responsible_lawyer,
        hearing=hearing,
        notes="Tanık listesi için süre istenecek.",
    )
    content = lawyer_client.get(task.get_absolute_url()).content.decode()
    assert "Bu duruşma için mazeret sunulacak." in content
    assert "Tanık listesi için süre istenecek." in content
    assert "Yeni duruşma var mı?" in content
    assert "Görevi Tamamla" in content
    assert "Dilekçeler" not in content


def test_close_hearing_task_attended_requires_decisions_and_client_info(case_factory):
    case = case_factory()
    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(hours=2),
    )
    task = Task.objects.create(
        case=case,
        title="Duruşma görevi",
        due_date=timezone.localdate(),
        task_type=TaskType.objects.first(),
        assignee=case.responsible_lawyer,
        reviewer=None,
        hearing=hearing,
    )

    # 1. Karar yazılmadıysa hata vermeli
    with pytest.raises(ValidationError, match="kararları girmelisiniz"):
        services.perform(
            task=task,
            key="close",
            user=case.responsible_lawyer,
            hearing_outcome="attended",
            hearing_decisions="",
        )

    # 2. Müvekkil bilgisi seçilmediyse hata vermeli
    with pytest.raises(ValidationError, match="Müvekkile bilgi verilip verilmediğini"):
        services.perform(
            task=task,
            key="close",
            user=case.responsible_lawyer,
            hearing_outcome="attended",
            hearing_decisions="Bilirkişi raporu beklenmesine karar verildi.",
            client_informed=None,
        )

    # 3. Bilgi verilmedi seçilip sebep yazılmadıysa hata vermeli
    with pytest.raises(ValidationError, match="sebebini yazmalısınız"):
        services.perform(
            task=task,
            key="close",
            user=case.responsible_lawyer,
            hearing_outcome="attended",
            hearing_decisions="Bilirkişi raporu beklenmesine karar verildi.",
            client_informed=False,
            client_not_informed_reason="",
        )

    # 4. Bilgi verilmedi + sebep yazıldı -> başarıyla kapanmalı
    services.perform(
        task=task,
        key="close",
        user=case.responsible_lawyer,
        hearing_outcome="attended",
        hearing_decisions="Bilirkişi raporu beklenmesine karar verildi.",
        client_informed=False,
        client_not_informed_reason="Müvekkil yurtdışında, telefon kapalı.",
    )

    task.refresh_from_db()
    hearing.refresh_from_db()

    assert task.status == TaskStatus.DONE
    assert task.hearing_outcome == "attended"
    assert hearing.status == HearingStatus.HELD
    assert hearing.decisions == "Bilirkişi raporu beklenmesine karar verildi."
    assert hearing.client_informed is False
    assert hearing.client_not_informed_reason == "Müvekkil yurtdışında, telefon kapalı."


def test_close_hearing_task_attended_client_informed_success(case_factory):
    case = case_factory()
    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(hours=2),
    )
    task = Task.objects.create(
        case=case,
        title="Duruşma görevi",
        due_date=timezone.localdate(),
        task_type=TaskType.objects.first(),
        assignee=case.responsible_lawyer,
        reviewer=None,
        hearing=hearing,
    )

    services.perform(
        task=task,
        key="close",
        user=case.responsible_lawyer,
        hearing_outcome="attended",
        hearing_decisions="Tanık dinlendi, sonraki celse 12.03.2027.",
        client_informed=True,
    )

    task.refresh_from_db()
    hearing.refresh_from_db()

    assert task.status == TaskStatus.DONE
    assert hearing.status == HearingStatus.HELD
    assert hearing.client_informed is True
    assert "Tanık dinlendi" in hearing.result

    event = CaseEvent.objects.filter(case=case, kind=CaseEvent.Kind.HEARING).first()
    assert event is not None
    assert "Müvekkile bilgi verildi" in event.description


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


def test_hearing_task_create_view_workflow(lawyer_client, case_factory):
    from django.urls import reverse

    from apps.cases.hearing_tasks import get_or_create_hearing_task_type

    case = case_factory()
    hearing = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(days=2),
        authority="İstanbul 1. Asliye Hukuk Mahkemesi",
        room="3",
        notes="Tanık listesi için süre istenecek.",
    )

    url = reverse("hearings:task_create", args=[hearing.pk])

    # 1. GET isteği formu döndürür
    response = lawyer_client.get(url)
    assert response.status_code == 200
    assert "form" in response.context
    assert response.context["form"]["notes"].value() == "Tanık listesi için süre istenecek."
    assert "Duruşma notu" in response.content.decode()
    assert "Duruşma Saati:" not in response.content.decode()
    assert "Salon: 3" in response.content.decode()
    assert "task_type" not in response.context["form"].fields

    # 2. POST ile görev oluşturulması
    task_type = get_or_create_hearing_task_type()
    post_data = {
        "task_type": str(task_type.pk),
        "title": "DURUŞMA TAKİP GÖREVİ",
        "case": str(case.pk),
        "client": str(case.client.pk),
        "assignee": str(case.responsible_lawyer.pk),
        "reviewer": "",
        "due_date": (timezone.now() + dt.timedelta(days=2)).date().isoformat(),
        "excuse_submitted": "on",
        "is_remote": "on",
        "notes": "Ön inceleme duruşması",
    }
    response = lawyer_client.post(url, post_data, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") == "true"

    hearing.refresh_from_db()
    assert hearing.assigned_to == case.responsible_lawyer
    assert hearing.excuse_submitted is True
    assert hearing.is_remote is True
    from apps.agenda.google_sync import hearing_to_google_payload

    assert "E-duruşma" in hearing_to_google_payload(hearing)["summary"]
    assert hearing.tasks.count() == 1

    task = hearing.tasks.first()
    assert task.title == "DURUŞMA TAKİP GÖREVİ"
    assert task.task_type == task_type
    assert task_type.points == 2
    assert task.client == case.client
    assert task.notes == "Ön inceleme duruşması"

    # 3. Görev zaten varsa GET isteği doğrudan göreve yönlendirir
    resp_redirect = lawyer_client.get(url)
    assert resp_redirect.status_code == 302
    assert resp_redirect.url == task.get_absolute_url()
    response = lawyer_client.get(url, HTTP_HX_REQUEST="true")
    assert response.headers["HX-Redirect"] == task.get_absolute_url()


def test_hearing_events_show_information_regardless_of_connected_task(case_factory):
    from apps.agenda.services import hearing_events
    from apps.cases.hearing_tasks import get_or_create_hearing_task_type

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
    task_type = get_or_create_hearing_task_type()
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
    assert all(not event.url and event.client_name for event in events)


def test_calendar_hearing_opens_information_not_task_creation(lawyer_client, case_factory):
    from django.urls import reverse

    case = case_factory()
    from apps.clients.models import ClientAppointment

    hearing = Hearing.objects.create(case=case, starts_at=timezone.now(), authority="Örnek mahkeme")
    other = Hearing.objects.create(case=case, starts_at=timezone.now() + dt.timedelta(hours=1))
    task = Task.objects.create(
        case=case,
        client=case.client,
        title="Bağlı görev",
        due_date=timezone.localdate(),
        task_type=TaskType.objects.first(),
        assignee=case.responsible_lawyer,
        hearing=other,
    )
    ClientAppointment.objects.create(
        client=case.client, title="Örnek görüşme", starts_at=timezone.now()
    )
    url = reverse("hearings:task_create", args=[hearing.pk])
    for view in ("month", "week"):
        response = lawyer_client.get(reverse("agenda:calendar"), {"view": view})
        content = response.content.decode()
        assert 'data-bs-target="#calendarEventModal"' in content
        assert f'hx-get="{url}"' not in content
        assert task.get_absolute_url() not in content
        assert 'data-event-location="Örnek mahkeme"' in content
        assert 'data-event-source="Randevu"' in content
    response = lawyer_client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert "Duruşma İçin Görev Oluştur" in response.content.decode()


def test_hearing_task_creation_respects_case_visibility(
    lawyer_client, case_factory, client_factory, admin_user
):
    from django.urls import reverse

    office = OfficeSettings.load()
    office.case_visibility_mode = OfficeSettings.CaseVisibilityMode.RESTRICTED
    office.save()
    client = client_factory(responsible_lawyer=admin_user, responsible_intern=None)
    hearing = Hearing.objects.create(case=case_factory(client=client), starts_at=timezone.now())
    url = reverse("hearings:task_create", args=[hearing.pk])
    assert lawyer_client.get(url).status_code == 404
    assert lawyer_client.post(url, {}).status_code == 404
