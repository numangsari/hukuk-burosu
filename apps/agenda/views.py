import calendar
import datetime as dt
from collections import defaultdict

from django.utils import timezone
from django.views.generic import TemplateView

from .services import events_between

MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]  # fmt: skip
WEEKDAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def _parse_date(value: str | None) -> dt.date:
    try:
        return dt.date.fromisoformat(value) if value else timezone.localdate()
    except ValueError:
        return timezone.localdate()


def group_by_day(events) -> dict[dt.date, list]:
    days = defaultdict(list)
    for ev in events:
        for d in ev.days:
            days[d].append(ev)
    return days


class AgendaView(TemplateView):
    template_name = "agenda/calendar.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        view = "week" if self.request.GET.get("view") == "week" else "month"
        anchor = _parse_date(self.request.GET.get("date"))
        today = timezone.localdate()

        if view == "month":
            weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(anchor.year, anchor.month)
            start, end = weeks[0][0], weeks[-1][-1] + dt.timedelta(days=1)
            first = anchor.replace(day=1)
            prev = (first - dt.timedelta(days=1)).replace(day=1)
            nxt = (first + dt.timedelta(days=32)).replace(day=1)
            title = f"{MONTHS[anchor.month - 1]} {anchor.year}"
        else:
            start = anchor - dt.timedelta(days=anchor.weekday())
            end = start + dt.timedelta(days=7)
            weeks = [[start + dt.timedelta(days=i) for i in range(7)]]
            prev, nxt = start - dt.timedelta(days=7), start + dt.timedelta(days=7)
            last = end - dt.timedelta(days=1)
            title = (
                f"{start.day} {MONTHS[start.month - 1]} – {last.day} {MONTHS[last.month - 1]} "
                f"{last.year}"
            )

        result = events_between(start, end)
        by_day = group_by_day(result.events)
        ctx.update(
            view=view,
            title=title,
            today=today,
            anchor=anchor,
            prev=prev,
            next=nxt,
            weekdays=WEEKDAYS,
            weeks=[
                [
                    {"date": d, "events": by_day.get(d, []), "in_month": d.month == anchor.month}
                    for d in w
                ]
                for w in weeks
            ],
            agenda=result,
        )
        return ctx
