import datetime as dt

from django.db.models import Q
from django.utils import timezone
from django.views.generic import TemplateView

from apps.agenda.services import combined_events
from apps.agenda.views import group_by_day
from apps.cases.models import Service
from apps.tasks.models import OPEN_STATUSES, Task, TaskStatus

AGENDA_DAYS = 7
HOME_TASK_LIMIT = 25


def greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Günaydın"
    if 12 <= hour < 18:
        return "İyi günler"
    return "İyi akşamlar"


def active_tasks_for(user):
    """Kullanıcının üzerindeki işler: sorumlu olduğu açık görevler (kontrolde olanlar hariç)
    ve kontrolünü bekleyen görevler. En acil (son günü en yakın) üstte."""
    return (
        Task.objects.filter(
            Q(assignee=user, status__in=[s for s in OPEN_STATUSES if s != TaskStatus.REVIEW])
            | Q(reviewer=user, status=TaskStatus.REVIEW)
        )
        .select_related("task_type", "case", "client", "assignee", "reviewer")
        .order_by("due_date", "pk")
    )


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.localtime()
        today = now.date()
        result = combined_events(today, today + dt.timedelta(days=AGENDA_DAYS))
        by_day = group_by_day(result.events)
        tasks = active_tasks_for(user)
        ctx.update(
            greeting=greeting(now.hour),
            my_tasks=tasks[:HOME_TASK_LIMIT],
            my_task_count=tasks.count(),
            agenda=result,
            agenda_days=[
                {"date": d, "events": by_day[d]}
                for d in (today + dt.timedelta(days=i) for i in range(AGENDA_DAYS))
                if by_day.get(d)
            ],
            overdue_services=Service.objects.filter(is_done=False, deadline__lt=today)
            .select_related("case")
            .order_by("deadline")[:10],
            today=today,
            tomorrow=today + dt.timedelta(days=1),
        )
        return ctx
