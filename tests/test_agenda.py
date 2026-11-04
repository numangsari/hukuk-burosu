import datetime as dt

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.agenda import services
from apps.agenda.services import CalendarError, events_between, parse_events
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db

# Uydurma örnek takvim: saatli, tüm gün (2 günlük) ve haftalık tekrar eden etkinlik.
ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//TR
BEGIN:VEVENT
UID:1@test
SUMMARY:Duruşma - Örnek
DTSTART:20261105T070000Z
DTEND:20261105T080000Z
LOCATION:İstanbul Adliyesi
END:VEVENT
BEGIN:VEVENT
UID:2@test
SUMMARY:Seminer
DTSTART;VALUE=DATE:20261106
DTEND;VALUE=DATE:20261108
END:VEVENT
BEGIN:VEVENT
UID:3@test
SUMMARY:Haftalık toplantı
DTSTART;TZID=Europe/Istanbul:20261102T090000
DTEND;TZID=Europe/Istanbul:20261102T093000
RRULE:FREQ=WEEKLY;COUNT=3
END:VEVENT
END:VCALENDAR
"""

FAKE_URL = "https://calendar.google.com/calendar/ical/test/private-x/basic.ics"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_parse_events_local_time_all_day_and_recurrence():
    events = parse_events(ICS, dt.date(2026, 11, 1), dt.date(2026, 11, 30))
    titles = [e.title for e in events]
    assert titles.count("Haftalık toplantı") == 3
    hearing = next(e for e in events if e.title.startswith("Duruşma"))
    assert hearing.time_label == "10:00–11:00"  # UTC 07:00 -> İstanbul 10:00
    assert hearing.location == "İstanbul Adliyesi"
    seminar = next(e for e in events if e.title == "Seminer")
    assert seminar.all_day and seminar.time_label == "Tüm gün"
    assert seminar.days == [dt.date(2026, 11, 6), dt.date(2026, 11, 7)]  # DTEND hariç
    assert seminar.display_end == dt.date(2026, 11, 7)


def test_not_configured():
    assert events_between(dt.date(2026, 11, 1), dt.date(2026, 11, 8)).configured is False


def test_fetch_cached_and_stale_fallback(monkeypatch):
    office = OfficeSettings.load()
    office.calendar_ics_url = FAKE_URL
    office.save()
    calls = []
    monkeypatch.setattr(services, "fetch_ics", lambda url: calls.append(url) or ICS)
    r1 = events_between(dt.date(2026, 11, 1), dt.date(2026, 11, 8))
    events_between(dt.date(2026, 11, 1), dt.date(2026, 11, 8))
    assert len(calls) == 1  # ikinci istek önbellekten
    assert r1.events and not r1.error

    # Taze kopya süresi dolduktan sonra Google'a ulaşılamazsa bayat kopya gösterilir.
    cache.delete(services._cache_key(FAKE_URL, "fresh"))

    def fail(url):
        raise CalendarError("Google Takvim'e ulaşılamadı.")

    monkeypatch.setattr(services, "fetch_ics", fail)
    r2 = events_between(dt.date(2026, 11, 1), dt.date(2026, 11, 8))
    assert r2.stale and r2.events and "son alınan" in r2.error


def test_fetch_error_without_cache(monkeypatch):
    office = OfficeSettings.load()
    office.calendar_ics_url = FAKE_URL
    office.save()

    def fail(url):
        raise CalendarError("Google Takvim'e ulaşılamadı.")

    monkeypatch.setattr(services, "fetch_ics", fail)
    r = events_between(dt.date(2026, 11, 1), dt.date(2026, 11, 8))
    assert r.configured and not r.events and r.error


def test_calendar_page_month_and_week(lawyer_client, monkeypatch):
    office = OfficeSettings.load()
    office.calendar_ics_url = FAKE_URL
    office.save()
    monkeypatch.setattr(services, "fetch_ics", lambda url: ICS)
    r = lawyer_client.get(reverse("agenda:calendar"), {"date": "2026-11-05"})
    html = r.content.decode()
    assert "Kasım 2026" in html and "Duruşma - Örnek" in html
    assert 'data-bs-target="#googleEventModal"' in html
    assert 'data-event-location="İstanbul Adliyesi"' in html
    assert 'data-event-end="07.11.2026"' in html
    assert "Yalnızca görüntüleme" in html
    assert '<h1 class="page-title mb-0">Takvim</h1>' in html
    assert "Duruşma Listesi" in html and "Ajanda &amp; Duruşmalar" not in html
    r = lawyer_client.get(reverse("agenda:calendar"), {"view": "week", "date": "2026-11-05"})
    assert "2 Kasım – 8 Kasım 2026" in r.content.decode()
    assert FAKE_URL not in r.content.decode()
    r = lawyer_client.get(reverse("agenda:calendar"), {"view": "list"})
    assert '<h1 class="page-title mb-0">Duruşma Listesi</h1>' in r.content.decode()
    assert 'aria-label="Takvim aralığı"' not in r.content.decode()


def test_calendar_shows_hearings_not_tasks_and_avoids_google_duplicates(
    lawyer_client, case_factory, monkeypatch
):
    from django.utils import timezone

    from apps.cases.models import Hearing
    from apps.office.models import TaskType
    from apps.tasks.models import Task

    case = case_factory()
    now = timezone.localtime().replace(second=0, microsecond=0)
    Hearing.objects.create(case=case, starts_at=now, google_event_id="managed123")
    Task.objects.create(
        case=case,
        title="Takvimde görünmeyen görev",
        due_date=now.date(),
        task_type=TaskType.objects.first(),
        assignee=case.responsible_lawyer,
    )
    office = OfficeSettings.load()
    office.calendar_ics_url = FAKE_URL
    office.save()
    calendar = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:managed123@google.com\n"
        f"DTSTART:{now:%Y%m%dT%H%M%S}\nSUMMARY:Tekrarlanan kayıt\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:external@google.com\n"
        f"DTSTART:{now:%Y%m%dT%H%M%S}\nSUMMARY:Harici toplantı\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    monkeypatch.setattr(services, "fetch_ics", lambda url: calendar)
    for view in ("month", "week"):
        response = lawyer_client.get(reverse("agenda:calendar"), {"view": view, "date": now.date()})
        events = response.context["agenda"].events
        assert any(event.source == "hearing" for event in events)
        assert any(event.title == "Harici toplantı" for event in events)
        assert not any(
            event.title == "Tekrarlanan kayıt" or event.source == "task" for event in events
        )


def test_google_api_calendar_read_is_paginated_and_read_only(monkeypatch):
    from unittest.mock import MagicMock

    from apps.agenda import google_sync

    office = OfficeSettings.load()
    office.google_calendar_api_enabled = True
    office.google_calendar_id = "test-calendar"
    office.calendar_ics_url = ""
    office.save()
    service = MagicMock()
    service.events.return_value.list.return_value.execute.side_effect = [
        {
            "items": [
                {
                    "id": "first",
                    "summary": "Toplantı",
                    "start": {"dateTime": "2026-11-05T10:00:00+03:00"},
                    "end": {"dateTime": "2026-11-05T11:00:00+03:00"},
                }
            ],
            "nextPageToken": "next",
        },
        {
            "items": [
                {
                    "id": "second",
                    "summary": "Tüm gün",
                    "start": {"date": "2026-11-06"},
                    "end": {"date": "2026-11-07"},
                }
            ]
        },
    ]
    monkeypatch.setattr(
        google_sync, "get_calendar_service", lambda office: (service, "test-calendar")
    )
    result = services.events_between(dt.date(2026, 11, 1), dt.date(2026, 11, 8))
    assert [event.title for event in result.events] == ["Toplantı", "Tüm gün"]
    assert service.events.return_value.list.call_count == 2
    service.events.return_value.insert.assert_not_called()
    service.events.return_value.patch.assert_not_called()
    service.events.return_value.delete.assert_not_called()


def test_calendar_hides_restricted_case_and_its_google_copy(
    lawyer_client, case_factory, client_factory, admin_user, monkeypatch
):
    from django.utils import timezone

    from apps.cases.models import Hearing

    office = OfficeSettings.load()
    office.case_visibility_mode = OfficeSettings.CaseVisibilityMode.RESTRICTED
    office.calendar_ics_url = FAKE_URL
    office.save()
    other_client = client_factory(responsible_lawyer=admin_user, responsible_intern=None)
    case = case_factory(client=other_client)
    now = timezone.localtime().replace(second=0, microsecond=0)
    Hearing.objects.create(case=case, starts_at=now, google_event_id="private-id")
    calendar = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:private-id@google.com\n"
        f"DTSTART:{now:%Y%m%dT%H%M%S}\nSUMMARY:Gizli kayıt\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    monkeypatch.setattr(services, "fetch_ics", lambda url: calendar)
    response = lawyer_client.get(reverse("agenda:calendar"), {"date": now.date()})
    assert not response.context["agenda"].events


@pytest.mark.parametrize("configured", [False, True])
def test_home_shows_tasks_calendar_shows_appointments_and_google_events(
    lawyer_client, case_factory, monkeypatch, configured
):
    from django.utils import timezone

    from apps.cases.models import Hearing
    from apps.clients.models import ClientAppointment
    from apps.office.models import TaskType
    from apps.tasks.models import Task

    case = case_factory()
    today = timezone.localdate()
    now = timezone.now()
    hearing = Hearing.objects.create(
        case=case, starts_at=now - dt.timedelta(days=10), authority="Eski duruşma"
    )
    appointment = ClientAppointment.objects.create(
        client=case.client, title="Eski randevu", starts_at=now
    )
    task = Task.objects.create(
        case=case,
        title="Örnek görev",
        due_date=today,
        task_type=TaskType.objects.first(),
        assignee=case.responsible_intern,
        reviewer=case.responsible_lawyer,
    )
    office = OfficeSettings.load()
    office.calendar_ics_url = FAKE_URL if configured else ""
    office.save()
    calendar = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:only-google@test\n"
        f"DTSTART;VALUE=DATE:{today:%Y%m%d}\nSUMMARY:Google örnek etkinlik\n"
        "END:VEVENT\nBEGIN:VEVENT\nUID:meeting@test\n"
        f"DTSTART:{today:%Y%m%d}T120000Z\nSUMMARY:Google toplantı\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    monkeypatch.setattr(services, "fetch_ics", lambda url: calendar)
    for url, params in [("/", {}), (reverse("agenda:calendar"), {"date": today.isoformat()})]:
        response = lawyer_client.get(url, params)
        assert response.status_code == 200
        events = response.context["agenda"].events
        if url == "/":
            assert any(e.title == task.title for e in events)
            assert '<span class="t">GÖREV</span>' in response.content.decode()
        else:
            assert not any(e.source == "task" for e in events)
            assert any(e.title == "Randevu: Eski randevu" for e in events)
            if configured:
                assert any(e.title == "Google örnek etkinlik" for e in events)
        html = response.content.decode()
        assert "WhatsApp mesajları" not in html
        if not configured and url != "/":
            assert "Google Takvim bağlı değil" in html
    assert Hearing.objects.filter(pk=hearing.pk).exists()
    assert ClientAppointment.objects.filter(pk=appointment.pk).exists()


@pytest.mark.parametrize("status", ["active", "review", "done"])
def test_task_deadlines_only_appear_on_due_date(case_factory, status):
    from apps.office.models import TaskType
    from apps.tasks.models import Task

    case = case_factory()
    due = dt.date(2026, 11, 5)
    task = Task.objects.create(
        case=case,
        title="Son gün denemesi",
        due_date=due,
        status=status,
        task_type=TaskType.objects.first(),
        assignee=case.responsible_intern,
        reviewer=case.responsible_lawyer,
    )
    assert not services.task_events(due - dt.timedelta(days=1), due)
    assert not services.task_events(due + dt.timedelta(days=1), due + dt.timedelta(days=2))
    events = services.task_events(due, due + dt.timedelta(days=1))
    if status == "done":
        assert not events
    else:
        assert len(events) == 1 and events[0].title == task.title
        responsible = task.reviewer if status == "review" else task.assignee
        assert str(responsible) in events[0].location


def test_google_connection_failure_does_not_hide_tasks(case_factory, monkeypatch):
    from apps.office.models import TaskType
    from apps.tasks.models import Task

    case = case_factory()
    due = dt.date(2026, 11, 5)
    task = Task.objects.create(
        case=case,
        title="Bağlantı olmadan görev",
        due_date=due,
        task_type=TaskType.objects.first(),
        assignee=case.responsible_intern,
        reviewer=case.responsible_lawyer,
    )
    office = OfficeSettings.load()
    office.calendar_ics_url = FAKE_URL
    office.save()

    def fail(url):
        raise CalendarError("Google Takvim'e ulaşılamadı.")

    monkeypatch.setattr(services, "fetch_ics", fail)
    result = services.combined_events(due, due + dt.timedelta(days=1))
    assert result.error and result.configured
    assert [event.title for event in result.events] == [task.title]
