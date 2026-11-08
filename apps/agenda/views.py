import calendar
import datetime as dt
from collections import defaultdict

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import User
from apps.cases.forms import ATTENDANCE_CHOICES
from apps.core.pagination import page_size

from .services import calendar_events

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

        result = calendar_events(start, end, user=self.request.user)
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
            from apps.cases.hearing_list import list_context

            info = list_context(self.request)
            paginator = Paginator(info.pop("queryset"), page_size(self.request, 25))
            page_obj = paginator.get_page(self.request.GET.get("page", 1))
            ctx.update(
                info,
                hearings=page_obj,
                page_obj=page_obj,
                lawyers=User.objects.filter(is_active=True)
                .exclude(role__in=[User.Role.PARALEGAL, User.Role.SECRETARY, User.Role.ACCOUNTANT])
                .order_by("first_name", "last_name"),
                attendance_choices=ATTENDANCE_CHOICES,
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
