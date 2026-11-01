import datetime as dt

from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.views.generic import TemplateView

from apps.agenda.services import events_between
from apps.agenda.views import group_by_day
from apps.tasks.models import OPEN_STATUSES, Task, TaskEvent, TaskStatus

AGENDA_DAYS = 7
HOME_TASK_LIMIT = 25


def greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Günaydın"
    if 12 <= hour < 18:
        return "İyi günler"
    return "İyi akşamlar"


def _home_tasks(**filters):
    return (
        Task.objects.filter(**filters)
        .select_related("task_type", "case", "client", "assignee", "reviewer")
        .order_by("due_date", "pk")
    )


def own_tasks_for(user):
    """Sorumlu olduğu açık görevler (kontrole gönderdikleri hariç). En acil üstte.
    Revizyon istenenlere kontrolcünün son revizyon notu eklenir."""
    last_revision_note = (
        TaskEvent.objects.filter(task=OuterRef("pk"), kind=TaskEvent.Kind.REVISION)
        .order_by("-created_at")
        .values("comment")[:1]
    )
    return _home_tasks(
        assignee=user, status__in=[s for s in OPEN_STATUSES if s != TaskStatus.REVIEW]
    ).annotate(revision_note=Subquery(last_revision_note))


def approved_unseen_for(user):
    """Onaylanmış ama sorumlunun henüz açıp görmediği görevler."""
    return _home_tasks(assignee=user, status=TaskStatus.DONE, approval_seen=False).order_by(
        "-completed_at"
    )


def review_tasks_for(user):
    """Kontrolünü bekleyen görevler. En acil üstte."""
    return _home_tasks(reviewer=user, status=TaskStatus.REVIEW)


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.localtime()
        today = now.date()
        result = events_between(today, today + dt.timedelta(days=AGENDA_DAYS))
        by_day = group_by_day(result.events)
        own = own_tasks_for(user)
        # Stajyerler kontrolcü olmadığı için onlarda "Kontrolümü bekleyenler" paneli yok.
        show_review = user.role != user.Role.INTERN
        if show_review:
            review = review_tasks_for(user)
            ctx.update(review_tasks=review[:HOME_TASK_LIMIT], review_task_count=review.count())
        ctx.update(
            greeting=greeting(now.hour),
            show_review=show_review,
            approved_tasks=approved_unseen_for(user)[:HOME_TASK_LIMIT],
            own_tasks=own[:HOME_TASK_LIMIT],
            own_task_count=own.count(),
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
