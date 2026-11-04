"""Ofisin Google Takvim'ini gizli iCal (ICS) adresinden salt okunur olarak çeker.

Ham ICS metni önbellekte 5 dakika tutulur. Google'a ulaşılamazsa son başarılı kopya
("stale") 1 güne kadar gösterilir ve kullanıcıya uyarı verilir.
"""

import datetime as dt
import hashlib
import logging
import urllib.request
from dataclasses import dataclass, field

import icalendar
import recurring_ical_events
from django.core.cache import cache
from django.utils import timezone

from apps.office.models import OfficeSettings

log = logging.getLogger(__name__)

FRESH_TTL = 5 * 60
STALE_TTL = 24 * 60 * 60
MAX_BYTES = 5 * 1024 * 1024


class CalendarError(Exception):
    pass


@dataclass
class Event:
    title: str
    start: dt.datetime | dt.date
    end: dt.datetime | dt.date | None
    all_day: bool
    location: str = ""
    description: str = ""
    days: list[dt.date] = field(default_factory=list)
    source: str = "google"  # Google takvimi, görev veya duruşma
    url: str = ""

    @property
    def start_date(self) -> dt.date:
        return self.start if self.all_day else self.start.date()

    @property
    def time_label(self) -> str:
        if self.source == "task":
            return "GÖREV"
        if self.source == "hearing":
            label = f"{self.start:%H:%M}"
            return f"DURUŞMA {label}" if not self.all_day else "DURUŞMA"
        if self.all_day:
            return "Tüm gün"
        label = f"{self.start:%H:%M}"
        if isinstance(self.end, dt.datetime) and self.end.date() == self.start.date():
            label += f"–{self.end:%H:%M}"
        return label


@dataclass
class AgendaResult:
    configured: bool
    events: list[Event] = field(default_factory=list)
    error: str = ""
    stale: bool = False


def _cache_key(url: str, kind: str) -> str:
    return f"agenda:{kind}:{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def fetch_ics(url: str) -> str:
    if not url.lower().startswith(("https://", "http://")):
        raise CalendarError("Takvim adresi http(s) ile başlamalı.")
    req = urllib.request.Request(url, headers={"User-Agent": "OzkurtHukuk/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (adres yalnızca yönetici girer)
            data = resp.read(MAX_BYTES + 1)
    except OSError as e:
        raise CalendarError("Google Takvim'e ulaşılamadı.") from e
    if len(data) > MAX_BYTES:
        raise CalendarError("Takvim verisi çok büyük.")
    text = data.decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text:
        raise CalendarError("Adres geçerli bir iCal takvimi döndürmedi.")
    return text


def get_ics_text(url: str) -> tuple[str, bool]:
    """(ics metni, bayat_mı) döndürür. Hiç veri yoksa CalendarError fırlatır."""
    fresh = cache.get(_cache_key(url, "fresh"))
    if fresh is not None:
        return fresh, False
    try:
        text = fetch_ics(url)
    except CalendarError:
        stale = cache.get(_cache_key(url, "stale"))
        if stale is not None:
            return stale, True
        raise
    cache.set(_cache_key(url, "fresh"), text, FRESH_TTL)
    cache.set(_cache_key(url, "stale"), text, STALE_TTL)
    return text, False


def _to_local(value):
    if isinstance(value, dt.datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value)
        return timezone.localtime(value)
    return value


def parse_events(text: str, start: dt.date, end: dt.date) -> list[Event]:
    """[start, end) aralığındaki etkinlikler; tekrar eden etkinlikler açılır."""
    cal = icalendar.Calendar.from_ical(text)
    events = []
    for comp in recurring_ical_events.of(cal).between(start, end):
        if comp.name != "VEVENT":
            continue
        s = _to_local(comp["DTSTART"].dt)
        e = _to_local(comp["DTEND"].dt) if comp.get("DTEND") else None
        all_day = not isinstance(s, dt.datetime)
        ev = Event(
            title=str(comp.get("SUMMARY", "")) or "(başlıksız)",
            start=s,
            end=e,
            all_day=all_day,
            location=str(comp.get("LOCATION", "")),
            description=str(comp.get("DESCRIPTION", "")),
        )
        # Etkinliğin görüneceği günler (tüm gün etkinliklerinde DTEND hariçtir).
        first = ev.start_date
        if e is None:
            last = first
        elif all_day:
            last = e - dt.timedelta(days=1)
        else:
            last = (e - dt.timedelta(seconds=1)).date()
        last = max(first, last)
        day = max(first, start)
        while day <= last and day < end:
            ev.days.append(day)
            day += dt.timedelta(days=1)
        events.append(ev)
    events.sort(
        key=lambda x: (x.start_date, not x.all_day, x.start if not x.all_day else dt.time())
    )
    return events


def events_between(start: dt.date, end: dt.date) -> AgendaResult:
    url = OfficeSettings.load().calendar_ics_url
    if not url:
        return AgendaResult(configured=False)
    try:
        text, stale = get_ics_text(url)
        events = parse_events(text, start, end)
    except CalendarError as e:
        return AgendaResult(configured=True, error=str(e))
    except (ValueError, KeyError) as e:
        log.warning("Takvim ayrıştırılamadı: %s", e)
        return AgendaResult(configured=True, error="Takvim verisi okunamadı.")
    result = AgendaResult(configured=True, events=events, stale=stale)
    if stale:
        result.error = "Google Takvim'e şu an ulaşılamıyor; son alınan veri gösteriliyor."
    return result


def task_events(start: dt.date, end: dt.date) -> list[Event]:
    """Açık görevleri son günlerinde, tüm gün süren etkinlikler olarak gösterir."""
    from apps.tasks.models import OPEN_STATUSES, Task, TaskStatus

    tasks = Task.objects.filter(
        status__in=OPEN_STATUSES, due_date__gte=start, due_date__lt=end
    ).select_related("case", "assignee", "reviewer")
    events = []
    for task in tasks:
        responsible = task.reviewer if task.status == TaskStatus.REVIEW else task.assignee
        events.append(
            Event(
                title=task.title,
                start=task.due_date,
                end=None,
                all_day=True,
                location=f"{task.case.archive_reference} · {responsible}",
                days=[task.due_date],
                source="task",
                url=task.get_absolute_url(),
            )
        )
    return events


def hearing_events(start: dt.date, end: dt.date) -> list[Event]:
    """[start, end) aralığındaki duruşmaları takvim etkinliği olarak gösterir."""
    from django.urls import reverse

    from apps.cases.models import Hearing

    start_dt = timezone.make_aware(dt.datetime.combine(start, dt.time.min))
    end_dt = timezone.make_aware(dt.datetime.combine(end, dt.time.min))
    hearings = (
        Hearing.objects.filter(starts_at__gte=start_dt, starts_at__lt=end_dt)
        .select_related("case", "case__client", "client")
        .order_by("starts_at")
    )
    events = []
    for h in hearings:
        local_s = timezone.localtime(h.starts_at)
        title = f"{h.get_kind_display()}: {h.title_display}"
        location = h.authority or (h.case.authority if h.case else "")
        if h.room:
            location += f" (Salon: {h.room})" if location else f"Salon: {h.room}"
        url = (
            h.case.get_absolute_url() + "#t-durusmalar"
            if h.case
            else (reverse("agenda:calendar") + "?view=list")
        )
        end_time = (
            timezone.localtime(h.ends_at) if h.ends_at else (local_s + dt.timedelta(minutes=30))
        )
        events.append(
            Event(
                title=title,
                start=local_s,
                end=end_time,
                all_day=False,
                location=location,
                description=h.notes or h.result or "",
                days=[local_s.date()],
                source="hearing",
                url=url,
            )
        )
    return events


def combined_events(start: dt.date, end: dt.date, include_hearings: bool = False) -> AgendaResult:
    """Google etkinlikleri ile açık görevleri aynı takvimde birleştirir."""
    result = events_between(start, end)
    all_events = list(result.events) + task_events(start, end)
    if include_hearings:
        all_events += hearing_events(start, end)
    result.events = sorted(
        all_events,
        key=lambda event: (
            event.start_date,
            not event.all_day,
            event.start if not event.all_day else dt.time(),
        ),
    )
    return result
