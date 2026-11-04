import calendar
import datetime as dt
from collections import defaultdict

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import User
from apps.cases.models import Case, Hearing, HearingKind, HearingStatus
from apps.core.pagination import page_size
from apps.core.permissions import filter_visible_cases

from .services import combined_events

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

    def render_to_response(self, context, **response_kwargs):
        if (
            self.request.headers.get("HX-Request")
            and not self.request.headers.get("HX-Boosted")
            and context.get("view") == "list"
        ):
            return render(self.request, "cases/_hearings_list_table.html", context)
        return super().render_to_response(context, **response_kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        raw_view = self.request.GET.get("view")
        if raw_view == "list":
            view = "list"
        elif raw_view == "week":
            view = "week"
        else:
            view = "month"

        anchor = _parse_date(self.request.GET.get("date"))
        today = timezone.localdate()

        if view == "month":
            weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(anchor.year, anchor.month)
            start, end = weeks[0][0], weeks[-1][-1] + dt.timedelta(days=1)
            first = anchor.replace(day=1)
            prev = (first - dt.timedelta(days=1)).replace(day=1)
            nxt = (first + dt.timedelta(days=32)).replace(day=1)
            title = f"{MONTHS[anchor.month - 1]} {anchor.year}"
        elif view == "week":
            start = anchor - dt.timedelta(days=anchor.weekday())
            end = start + dt.timedelta(days=7)
            weeks = [[start + dt.timedelta(days=i) for i in range(7)]]
            prev, nxt = start - dt.timedelta(days=7), start + dt.timedelta(days=7)
            last = end - dt.timedelta(days=1)
            title = (
                f"{start.day} {MONTHS[start.month - 1]} – {last.day} {MONTHS[last.month - 1]} "
                f"{last.year}"
            )
        else:
            weeks = []
            prev = anchor - dt.timedelta(days=30)
            nxt = anchor + dt.timedelta(days=30)
            title = "Duruşmalar ve Etkinlikler Listesi"
            start, end = today, today + dt.timedelta(days=30)

        result = combined_events(start, end)
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

        if view == "list":
            user = self.request.user
            visible_cases = filter_visible_cases(Case.objects.all(), user)
            base_qs = (
                Hearing.objects.filter(Q(case__in=visible_cases) | Q(case__isnull=True))
                .select_related(
                    "case", "case__client", "case__responsible_lawyer", "client", "assigned_to"
                )
                .prefetch_related("tasks")
            )
            now = timezone.now()
            scope = self.request.GET.get("scope", "upcoming")
            qs = base_qs

            if scope == "upcoming":
                qs = qs.filter(starts_at__gte=now).order_by("starts_at")
            elif scope == "today":
                qs = qs.filter(starts_at__date=today).order_by("starts_at")
            elif scope == "pending_result":
                qs = qs.filter(starts_at__lt=now, status=HearingStatus.PLANNED).order_by(
                    "starts_at"
                )
            elif scope == "past":
                qs = qs.filter(Q(starts_at__lt=now) & ~Q(status=HearingStatus.PLANNED)).order_by(
                    "-starts_at"
                )
            elif scope == "all":
                qs = qs.order_by("-starts_at")

            q = self.request.GET.get("q", "").strip()
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
                    | Q(room__icontains=q)
                )

            lawyer_id = self.request.GET.get("avukat")
            if lawyer_id:
                qs = qs.filter(
                    Q(case__responsible_lawyer_id=lawyer_id) | Q(assigned_to_id=lawyer_id)
                )

            kind = self.request.GET.get("tur")
            if kind:
                qs = qs.filter(kind=kind)

            status = self.request.GET.get("durum")
            if status:
                qs = qs.filter(status=status)

            paginator = Paginator(qs, page_size(self.request, 25))
            page_obj = paginator.get_page(self.request.GET.get("page", 1))

            today_count = base_qs.filter(starts_at__date=today).count()
            upcoming_count = base_qs.filter(starts_at__gte=now).count()
            pending_result_count = base_qs.filter(
                starts_at__lt=now, status=HearingStatus.PLANNED
            ).count()
            total_count = base_qs.count()

            lawyers = User.objects.filter(is_active=True).order_by("first_name", "last_name")

            ctx.update(
                hearings=page_obj,
                page_obj=page_obj,
                current_scope=scope,
                today_count=today_count,
                upcoming_count=upcoming_count,
                pending_result_count=pending_result_count,
                total_count=total_count,
                lawyers=lawyers,
                kinds=HearingKind.choices,
                statuses=HearingStatus.choices,
                now=now,
            )

        return ctx


class GoogleApiTestView(View):
    """Google Takvim API bağlantısını test eder veya toplu eşitleme yapar."""

    def post(self, request):
        if not (request.user.is_authenticated and request.user.is_office_admin):
            return HttpResponse('<div class="alert alert-danger">Yetkiniz yok.</div>', status=403)

        from .google_sync import sync_all_hearings_to_google, test_google_calendar_connection

        action = request.POST.get("action", "test")
        if action == "sync_all":
            res = sync_all_hearings_to_google()
            if res.get("success"):
                cls = "success"
                icon = "check-circle-fill"
                msg = (
                    f"Toplu aktarım tamamlandı: Toplam {res['total']} kayıttan "
                    f"{res['synced']} tanesi Google Takvim'e işlendi. ({res['errors']} hata)"
                )
            else:
                cls = "danger"
                icon = "exclamation-triangle-fill"
                msg = res.get("error", "Toplu eşitleme yapılamadı.")
            return HttpResponse(
                f'<div class="alert alert-{cls} alert-dismissible fade show mt-2 mb-0">'
                f'<i class="bi bi-{icon} me-2"></i>{msg}'
                f'<button type="button" class="btn-close" data-bs-dismiss="alert"></button>'
                f"</div>"
            )

        ok, msg = test_google_calendar_connection()
        cls = "success" if ok else "danger"
        icon = "check-circle-fill" if ok else "exclamation-triangle-fill"
        return HttpResponse(
            f'<div class="alert alert-{cls} alert-dismissible fade show mt-2 mb-0">'
            f'<i class="bi bi-{icon} me-2"></i>{msg}'
            f'<button type="button" class="btn-close" data-bs-dismiss="alert"></button>'
            f"</div>"
        )
