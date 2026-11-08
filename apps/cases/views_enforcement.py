from django.views.generic import ListView

from apps.core.list_export import ListExportMixin
from apps.core.pagination import page_size
from apps.core.text import tr_title
from apps.reports.base import Column

from . import seizure_types, stages
from .enforcement import RENEWAL_WARNING_DAYS, apply_filters, apply_sort, enforcement_base
from .models import CaseType, EnforcementType


class EnforcementListView(ListExportMixin, ListView):
    template_name = "cases/enforcement_list.html"
    context_object_name = "cases"
    export_title = "İcra İşlemleri"

    def export_columns(self):
        return [
            Column("Arşiv yeri", width=1.1),
            Column("Dosya", width=2.4),
            Column("İcra türü", width=1.2),
            Column("Müvekkil", width=2.0),
            Column("Sıfatı", width=1.0),
            Column("Aşama", width=1.4),
            Column("Haciz durumu", width=2.6),
            Column("Tebligat", "int", 0.8),
            Column("Haciz yenileme", "date", 1.1),
            Column("Son işlem", "date", 1.1),
        ]

    def export_row(self, case):
        seizures = "; ".join(
            f"{s.get_kind_display()}: {s.state_label or '—'}"
            for s in case.seizures.all()
            if s.is_active
        )
        return [
            case.archive_reference or "",
            tr_title(case.display_name),
            case.get_enforcement_type_display(),
            tr_title(case.client) if case.client else "",
            case.get_client_role_display() if case.client_role else "",
            case.stage_label if case.is_open else "Kapalı",
            seizures,
            case.notice_count,
            case.next_renewal,
            case.last_action.date() if case.last_action else None,
        ]

    def get_paginate_by(self, queryset):
        return page_size(self.request)

    def get_queryset(self):
        qs = enforcement_base(self.request.user).select_related("client", "responsible_lawyer")
        qs = qs.prefetch_related("seizures")
        qs = apply_filters(qs, self.request.GET)
        qs, self.sort = apply_sort(qs, self.request.GET.get("sort", "-last_action"))
        return qs

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["cases/_enforcement_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        from apps.accounts.models import User

        ctx = super().get_context_data(**kwargs)
        ctx["lawyers"] = User.objects.filter(role__in=["admin", "senior", "lawyer"], is_active=True)
        ctx["enforcement_types"] = EnforcementType.choices
        ctx["stage_choices"] = stages.open_stages(CaseType.ENFORCEMENT)
        ctx["seizure_kinds"] = seizure_types.KINDS
        ctx["renewal_days"] = RENEWAL_WARNING_DAYS
        return ctx
