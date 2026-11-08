"""Modül ana sayfalarının başlığındaki salt okunur özet satırı.

Sayılar kullanıcının rolüne ve dosya görünürlüğüne göre değişmez: herkese aynı büro geneli sayı
gösterilir. Parasal tutar veya bakiye içermez (bakiye yetkisi ayrıdır). Kısa süre önbelleğe alınır.
"""

import datetime as dt

from django.core.cache import cache
from django.utils import timezone

CACHE_SECONDS = 60


def _cases():
    from apps.cases.models import Case, CaseStatus

    qs = Case.objects.all()
    month = timezone.localdate().replace(day=1)
    return [
        ("Açık dosya", qs.filter(status=CaseStatus.OPEN).count()),
        ("Kapalı dosya", qs.filter(status=CaseStatus.CLOSED).count()),
        ("Müvekkilsiz", qs.filter(client__isnull=True, status=CaseStatus.OPEN).count()),
        ("Bu ay açılan", qs.filter(created_at__date__gte=month).count()),
    ]


def _clients():
    from apps.clients.models import Client

    month = timezone.localdate().replace(day=1)
    qs = Client.objects.all()
    return [
        ("Müvekkil", qs.count()),
        ("Açık dosyası olan", qs.filter(cases__status="open").distinct().count()),
        ("Bu ay eklenen", qs.filter(created_at__date__gte=month).count()),
    ]


def _tasks():
    from apps.tasks.models import OPEN_STATUSES, Task, TaskStatus

    today = timezone.localdate()
    open_qs = Task.objects.filter(status__in=OPEN_STATUSES)
    return [
        ("Açık görev", open_qs.count()),
        ("Kontrolde", Task.objects.filter(status=TaskStatus.REVIEW).count()),
        ("Geciken", open_qs.filter(due_date__lt=today).count()),
        ("Bugün biten", open_qs.filter(due_date=today).count()),
    ]


def _hearings():
    from apps.cases.models import Hearing, HearingStatus

    today = timezone.localdate()
    week_end = today + dt.timedelta(days=6 - today.weekday())
    month_end = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    qs = Hearing.objects.exclude(status=HearingStatus.CANCELLED)

    def between(start, end):
        return qs.filter(starts_at__date__gte=start, starts_at__date__lte=end).count()

    return [
        ("Bugün", between(today, today)),
        ("Bu hafta", between(today, week_end)),
        ("Bu ay", between(today, month_end)),
        ("Gelecek", qs.filter(starts_at__date__gte=today).count()),
    ]


def _accounting():
    from apps.accounting.models import LedgerEntry

    today = timezone.localdate()
    month = today.replace(day=1)
    qs = LedgerEntry.objects.filter(date__gte=month)
    return [
        ("Bu ay hareket", qs.filter(is_cancelled=False).count()),
        ("Bu ay iptal", qs.filter(is_cancelled=True).count()),
        ("Hesap dışı", LedgerEntry.objects.filter(excluded_from_balance=True).count()),
    ]


def _archive():
    from apps.cases.models import ArchiveFolder, Case, CaseStatus

    return [
        ("Klasör", ArchiveFolder.objects.count()),
        (
            "Arşiv yeri eksik",
            Case.objects.filter(archive_needs_review=True).count(),
        ),
        ("Kapalı dosya", Case.objects.filter(status=CaseStatus.CLOSED).count()),
    ]


def _notices():
    from apps.imports.models import PortalNotice

    qs = PortalNotice.objects.all()
    return [
        ("İşlem bekleyen", qs.filter(resolved_at__isnull=True).count()),
        ("Göreve bağlanan", qs.filter(resolution_task__isnull=False).count()),
        (
            "Görev gerekmeyen",
            qs.filter(resolved_at__isnull=False, resolution_task__isnull=True).count(),
        ),
    ]


def _enforcement():
    from apps.cases.enforcement import enforcement_stats

    return enforcement_stats()


def _home():
    tasks = dict(_tasks())
    hearings = dict(_hearings())
    notices = dict(_notices())
    return [
        ("Açık görev", tasks["Açık görev"]),
        ("Geciken görev", tasks["Geciken"]),
        ("Bugünkü duruşma", hearings["Bugün"]),
        ("Bekleyen tebligat", notices["İşlem bekleyen"]),
    ]


BUILDERS = {
    "home": _home,
    "cases": _cases,
    "clients": _clients,
    "tasks": _tasks,
    "hearings": _hearings,
    "accounting": _accounting,
    "archive": _archive,
    "notices": _notices,
    "enforcement": _enforcement,
}


def module_stats(key: str) -> list:
    """[(etiket, sayı)] listesi; hata olursa sayfayı bozmamak için boş döner."""
    builder = BUILDERS.get(key)
    if builder is None:
        return []
    cache_key = f"module-stats:{key}"
    data = cache.get(cache_key)
    if data is None:
        try:
            data = builder()
        except Exception:  # özet satırı sayfanın çalışmasını engellememeli
            return []
        cache.set(cache_key, data, CACHE_SECONDS)
    return data
