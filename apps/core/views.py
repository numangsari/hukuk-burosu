from django.db.models import Count, Q
from django.utils import timezone
from django.views.generic import TemplateView

from apps.cases.models import Case, CaseStatus, CaseType
from apps.clients.models import Client


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
        user = self.request.user
        now = timezone.localtime()
        open_cases = Case.objects.exclude(status=CaseStatus.CLOSED)
        mine = Q(responsible_lawyer=user) | Q(responsible_intern=user)

        by_type = dict(
            open_cases.values_list("case_type")
            .annotate(n=Count("pk"))
            .values_list("case_type", "n")
        )
        total_open = sum(by_type.values()) or 1
        ctx.update(
            greeting=greeting(now.hour),
            stats={
                "clients": Client.objects.filter(is_active=True).count(),
                "open_cases": open_cases.count(),
                "month_cases": Case.objects.filter(
                    created_at__year=now.year, created_at__month=now.month
                ).count(),
                "my_cases": open_cases.filter(mine).count(),
            },
            type_breakdown=[
                {
                    "label": label,
                    "value": value,
                    "count": by_type[value],
                    "pct": round(by_type[value] * 100 / total_open),
                }
                for value, label in CaseType.choices
                if by_type.get(value)
            ],
            recent_cases=Case.objects.select_related("client", "responsible_lawyer")[:6],
            my_clients=Client.objects.filter(is_active=True)
            .filter(Q(responsible_lawyer=user) | Q(responsible_intern=user))
            .annotate(case_count=Count("cases"))
            .order_by("-updated_at")[:5],
        )
        return ctx
