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
