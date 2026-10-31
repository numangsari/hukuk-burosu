import datetime as dt

from django.utils import timezone
from django.views.generic import TemplateView

from apps.agenda.services import events_between
from apps.agenda.views import group_by_day

AGENDA_DAYS = 7


def greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Günaydın"
    if 12 <= hour < 18:
        return "İyi günler"
    return "İyi akşamlar"


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.localtime()
        today = now.date()
        result = events_between(today, today + dt.timedelta(days=AGENDA_DAYS))
        by_day = group_by_day(result.events)
        ctx.update(
            greeting=greeting(now.hour),
            agenda=result,
            agenda_days=[
                {"date": d, "events": by_day[d]}
                for d in (today + dt.timedelta(days=i) for i in range(AGENDA_DAYS))
                if by_day.get(d)
            ],
            today=today,
            tomorrow=today + dt.timedelta(days=1),
        )
        return ctx
