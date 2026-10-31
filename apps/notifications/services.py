import datetime as dt

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Notification

REMINDER_INTERVAL = 5 * 60


def notify(user, title, *, url="", body="", kind=Notification.Kind.TASK, actor=None, key=""):
    """Kullanıcıya bildirim gönderir. Kişi kendi yaptığı işlem için bildirim almaz."""
    if user is None or not user.is_active or (actor is not None and actor.pk == user.pk):
        return None
    try:
        with transaction.atomic():
            return Notification.objects.create(
                user=user, title=title[:300], url=url, body=body[:500], kind=kind, key=key
            )
    except IntegrityError:  # aynı key ile daha önce gönderilmiş
        return None


def send_daily_reminders(today: dt.date | None = None) -> int:
    """Yakın/geçmiş görev ve tebligat son günleri ile bugün/yarınki duruşmalar.

    Gün içinde birden çok kez çağrılabilir; key sayesinde tekrar göndermez.
    """
    from apps.cases.models import Hearing, HearingStatus, Service
    from apps.tasks.models import OPEN_STATUSES, Task, TaskStatus

    today = today or timezone.localdate()
    tomorrow = today + dt.timedelta(days=1)
    sent = 0
    tasks = Task.objects.filter(status__in=OPEN_STATUSES, due_date__lte=tomorrow).select_related(
        "assignee", "reviewer"
    )
    for t in tasks:
        when = "yarın" if t.due_date == tomorrow else ("bugün" if t.due_date == today else "geçti")
        n = notify(
            t.reviewer if t.status == TaskStatus.REVIEW else t.assignee,
            f"Görevin son günü {when}: {t.title}",
            url=t.get_absolute_url(),
            kind=Notification.Kind.DEADLINE,
            key=f"due:{t.pk}:{today.isoformat()}:{t.due_date.isoformat()}:{t.status}",
        )
        sent += n is not None
    hearings = Hearing.objects.filter(
        status=HearingStatus.PLANNED, starts_at__date__gte=today, starts_at__date__lte=tomorrow
    ).select_related("case__responsible_lawyer", "case__responsible_intern")
    for h in hearings:
        when = "Bugün" if timezone.localtime(h.starts_at).date() == today else "Yarın"
        for user in {h.case.responsible_lawyer, h.case.responsible_intern}:
            n = notify(
                user,
                f"{when} {h.get_kind_display().lower()}: {h.case.subject}",
                body=f"{timezone.localtime(h.starts_at):%H:%M} · {h.authority}",
                url=h.case.get_absolute_url(),
                kind=Notification.Kind.HEARING,
                key=f"hearing:{h.pk}:{today.isoformat()}:{h.starts_at.isoformat()}",
            )
            sent += n is not None
    services = Service.objects.filter(is_done=False, deadline__lte=tomorrow).select_related(
        "case__responsible_lawyer", "case__responsible_intern"
    )
    for service in services:
        when = (
            "yarın"
            if service.deadline == tomorrow
            else ("bugün" if service.deadline == today else "geçti")
        )
        for user in {service.case.responsible_lawyer, service.case.responsible_intern}:
            n = notify(
                user,
                f"Tebligatın son günü {when}: {service.subject}",
                body=f"{service.case.archive_no} · {service.case.subject}",
                url=service.case.get_absolute_url(),
                kind=Notification.Kind.DEADLINE,
                key=f"service:{service.pk}:{today.isoformat()}:{service.deadline.isoformat()}",
            )
            sent += n is not None
    return sent


def _reminder_cache_key():
    return f"reminders:{timezone.localdate().isoformat()}"


def invalidate_reminders():
    cache.delete(_reminder_cache_key())


def run_daily_reminders_once():
    """Sayfa açılışında en çok beş dakika arayla; kayıt değişince hemen yeniden tarar."""
    key = _reminder_cache_key()
    if cache.add(key, True, REMINDER_INTERVAL):
        try:
            send_daily_reminders()
        except Exception:
            cache.delete(key)
            raise
