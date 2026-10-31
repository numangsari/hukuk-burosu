import datetime as dt

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Notification


def notify(user, title, *, url="", body="", kind=Notification.Kind.TASK, actor=None, key=""):
    """Kullanıcıya bildirim gönderir. Kişi kendi yaptığı işlem için bildirim almaz."""
    if user is None or not user.is_active or (actor is not None and actor.pk == user.pk):
        return None
    try:
        with transaction.atomic():
            return Notification.objects.create(
                user=user, title=title, url=url, body=body, kind=kind, key=key
            )
    except IntegrityError:  # aynı key ile daha önce gönderilmiş
        return None


def send_daily_reminders(today: dt.date | None = None) -> int:
    """Son günü yarın/bugün olan görevler ve yarınki duruşmalar için hatırlatma.

    Gün içinde birden çok kez çağrılabilir; key sayesinde tekrar göndermez.
    """
    from apps.cases.models import Hearing, HearingStatus
    from apps.tasks.models import OPEN_STATUSES, Task

    today = today or timezone.localdate()
    tomorrow = today + dt.timedelta(days=1)
    sent = 0
    tasks = Task.objects.filter(status__in=OPEN_STATUSES, due_date__lte=tomorrow).select_related(
        "assignee"
    )
    for t in tasks:
        when = "yarın" if t.due_date == tomorrow else ("bugün" if t.due_date == today else "geçti")
        n = notify(
            t.assignee,
            f"Görevin son günü {when}: {t.title}",
            url=t.get_absolute_url(),
            kind=Notification.Kind.DEADLINE,
            key=f"due:{t.pk}:{today.isoformat()}",
        )
        sent += n is not None
    hearings = Hearing.objects.filter(
        status=HearingStatus.PLANNED, starts_at__date=tomorrow
    ).select_related("case__responsible_lawyer", "case__responsible_intern")
    for h in hearings:
        for user in {h.case.responsible_lawyer, h.case.responsible_intern}:
            n = notify(
                user,
                f"Yarın {h.get_kind_display().lower()}: {h.case.subject}",
                body=f"{timezone.localtime(h.starts_at):%H:%M} · {h.authority}",
                url=h.case.get_absolute_url(),
                kind=Notification.Kind.HEARING,
                key=f"hearing:{h.pk}:{today.isoformat()}",
            )
            sent += n is not None
    return sent


def run_daily_reminders_once():
    """Günde bir kez hatırlatmaları çalıştırır (sayfa açılışında tetiklenir)."""
    key = f"reminders:{timezone.localdate().isoformat()}"
    if cache.add(key, True, 60 * 60 * 26):
        send_daily_reminders()
