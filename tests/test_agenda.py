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
    r = lawyer_client.get(reverse("agenda:calendar"), {"view": "week", "date": "2026-11-05"})
    assert "2 Kasım – 8 Kasım 2026" in r.content.decode()
    assert FAKE_URL not in r.content.decode()


@pytest.mark.parametrize("configured", [False, True])
def test_home_and_calendar_show_tasks_and_all_google_events(
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
    hearing = Hearing.objects.create(case=case, starts_at=now, authority="Eski duruşma")
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
        assert [e.title for e in events] == (
            ["Google örnek etkinlik", f"GÖREV: {task.title}", "Google toplantı"]
            if configured
            else [f"GÖREV: {task.title}"]
        )
        task_event = next(e for e in events if e.source == "task")
        assert task_event.all_day and task_event.days == [today]
        assert task_event.url == task.get_absolute_url()
        assert task_event.url in response.content.decode()
        html = response.content.decode()
        assert "Eski randevu" not in html and "Eski duruşma" not in html
        assert "WhatsApp mesajları" not in html
        if not configured:
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
        assert len(events) == 1 and events[0].title == f"GÖREV: {task.title}"
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
    assert [event.title for event in result.events] == [f"GÖREV: {task.title}"]
