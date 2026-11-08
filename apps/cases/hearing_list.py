"""Duruşma listesi: görünür duruşmalar, sekmeler (kapsam), filtreler ve sayaçlar."""

import datetime as dt

from django.db.models import Q
from django.utils import timezone

from apps.core.permissions import filter_visible_cases

from .models import LIST_KINDS, RESULT_KINDS, Case, Hearing, HearingStatus

SCOPES = ("upcoming", "past")


def base_hearings(user):
    visible_cases = filter_visible_cases(Case.objects.all(), user)
    return (
        Hearing.objects.filter(Q(case__in=visible_cases) | Q(case__isnull=True))
        .select_related("case", "case__client", "client", "assigned_to")
        .prefetch_related("tasks")
    )


def needs_action_q(today: dt.date) -> Q:
    """Yapılmış sayılan (saati geçmiş) duruşmalarda sonuç veya bilgilendirme eksik olanlar.

    `today` geriye dönük uyumluluk için alınır; sınır şu andır (`Hearing.is_done`).
    """
    has_client = Q(client__isnull=False) | Q(case__client__isnull=False)
    inform_missing = has_client & Q(client_informed_at__isnull=True) & ~Q(client_informed=True)
    return (
        Q(starts_at__lte=timezone.now(), kind__in=RESULT_KINDS)
        & ~Q(status=HearingStatus.CANCELLED)
        & (Q(result="") | inform_missing)
    )


def missing_info_q(today: dt.date) -> Q:
    """Yaklaşanlarda eksik bilgi: saati geçmişte sonuç ve bilgilendirme, gelmemişte sorumlu."""
    upcoming_no_lawyer = Q(
        starts_at__gt=timezone.now(), kind__in=RESULT_KINDS, assigned_to__isnull=True
    ) & ~Q(status=HearingStatus.CANCELLED)
    return needs_action_q(today) | upcoming_no_lawyer


def scoped(qs, scope: str, today: dt.date):
    if scope == "past":
        return qs.filter(starts_at__date__lt=today).order_by("-starts_at")
    return qs.filter(starts_at__date__gte=today).order_by("starts_at")  # upcoming


def apply_filters(qs, params):
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(case__official_no__icontains=q)
            | Q(case__subject__icontains=q)
            | Q(case__authority__icontains=q)
            | Q(authority__icontains=q)
            | Q(case__client__name__icontains=q)
            | Q(client__name__icontains=q)
            | Q(notes__icontains=q)
            | Q(result__icontains=q)
        )
    lawyer = params.get("avukat")
    if lawyer and str(lawyer).isdigit():
        qs = qs.filter(assigned_to_id=lawyer)
    attendance = params.get("katilim")
    if attendance == "excuse":
        qs = qs.filter(excuse_submitted=True)
    elif attendance == "remote":
        qs = qs.filter(is_remote=True, excuse_submitted=False)
    elif attendance == "attend":
        qs = qs.filter(is_remote=False, excuse_submitted=False)
    for key, lookup in (("baslangic", "starts_at__date__gte"), ("bitis", "starts_at__date__lte")):
        try:
            if params.get(key):
                qs = qs.filter(**{lookup: dt.date.fromisoformat(params[key])})
        except ValueError:
            pass
    return qs


def quick_ranges(today: dt.date) -> list[tuple[str, dt.date, dt.date]]:
    """Hızlı tarih filtreleri: bugün, bu hafta, gelecek hafta, bu ay."""
    monday = today - dt.timedelta(days=today.weekday())
    next_monday = monday + dt.timedelta(days=7)
    first = today.replace(day=1)
    next_first = (first + dt.timedelta(days=32)).replace(day=1)
    return [
        ("Bugün", today, today),
        ("Bu hafta", monday, monday + dt.timedelta(days=6)),
        ("Gelecek hafta", next_monday, next_monday + dt.timedelta(days=6)),
        ("Bu ay", first, next_first - dt.timedelta(days=1)),
    ]


def list_context(request) -> dict:
    """Liste sayfası bağlamı (sekmeler, tarih filtresi, süzülmüş duruşmalar)."""
    today = timezone.localdate()
    scope = request.GET.get("scope", "upcoming")
    if scope not in SCOPES:
        scope = "upcoming"
    base = base_hearings(request.user).filter(kind__in=LIST_KINDS)
    ranges = [
        {
            "label": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "active": request.GET.get("baslangic") == start.isoformat()
            and request.GET.get("bitis") == end.isoformat(),
        }
        for label, start, end in quick_ranges(today)
    ]
    return {
        "queryset": apply_filters(scoped(base, scope, today), request.GET),
        "current_scope": scope,
        "today": today,
        "now": timezone.now(),
        "quick_ranges": ranges,
        # Sekmelerde eksik bilgisi (sonuç/bilgilendirme) olan duruşma sayıları (uyarı rozeti).
        "attention_counts": {
            key: scoped(base, key, today)
            .filter(missing_info_q(today) if key == "upcoming" else needs_action_q(today))
            .count()
            for key in SCOPES
        },
    }
