from django.views.generic import ListView

from apps.core.list_export import ListExportMixin
from apps.core.pagination import page_size
from apps.core.scope import responsible_q, wants_mine
from apps.core.text import tr_title
from apps.reports.base import Column

from . import seizure_types
from .enforcement import (
    RENEWAL_WARNING_DAYS,
    ROLE_TABS,
    TABS,
    apply_filters,
    apply_sort,
    enforcement_base,
    side_names,
    tab_counts,
    tab_key,
    uyap_closing_reason,
)
from .models import EnforcementType


def _join(names):
    return "; ".join(tr_title(n) for n in names)


class EnforcementListView(ListExportMixin, ListView):
    template_name = "cases/enforcement_list.html"
    context_object_name = "cases"
    export_title = "İcra İşlemleri"

    def _layout(self):
        """Sekmeye göre değişen sütunlar ve başlıkları."""
        tab = tab_key(self.request.GET)
        return {
            "tab": tab,
            "creditor_label": "Alacaklı" if tab in ROLE_TABS else "Alacaklı / Müvekkil",
            "debtor_label": "Borçlu / Müvekkil" if tab == "borclu" else "Borçlu",
            "show_client": tab == "ucuncu",
            "show_seizure": tab == "haciz",
            "show_reason": tab == "islemsiz",
        }

    def export_columns(self):
        lay = self._layout()
        cols = [
            Column("Arşiv yeri", width=1.1),
            Column("Dosya", width=2.4),
            Column("İcra türü", width=1.2),
            Column(lay["creditor_label"], width=2.0),
            Column(lay["debtor_label"], width=2.0),
        ]
        if lay["show_client"]:
            cols.append(Column("Müvekkil (sıfatı)", width=2.0))
        cols.append(Column("Aşama", width=1.4))
        if lay["show_seizure"]:
            cols.append(Column("Haciz durumu", width=2.6))
        if lay["show_reason"]:
            cols.append(Column("Kapanma nedeni (UYAP)", width=2.0))
        cols.append(Column("Son işlem", "date", 1.1))
        return cols

    def export_row(self, case):
        lay = self._layout()
        row = [
            case.archive_reference or "",
            tr_title(case.display_name),
            case.get_enforcement_type_display(),
            _join(side_names(case, "creditor")),
            _join(side_names(case, "debtor")),
        ]
        if lay["show_client"]:
            who = tr_title(case.client) if case.client else ""
            row.append(f"{who} ({case.get_client_role_display()})" if case.client_role else who)
        row.append(case.stage_label if case.is_open else "Kapalı")
        if lay["show_seizure"]:
            row.append(
                "; ".join(b["title"] for b in seizure_types.kind_badges(case.seizures.all()))
            )
        if lay["show_reason"]:
            row.append(uyap_closing_reason(case))
        row.append(case.last_action.date() if case.last_action else None)
        return row

    def get_paginate_by(self, queryset):
        return page_size(self.request)

    def _scoped_base(self):
        qs = enforcement_base(self.request.user)
        if wants_mine(self.request.GET):
            qs = qs.filter(responsible_q(self.request.user))
        return qs

    def get_queryset(self):
        qs = self._scoped_base().select_related("client", "responsible_lawyer")
        qs = qs.prefetch_related("seizures", "party_links__party", "co_client_links__client")
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
        ctx["renewal_days"] = RENEWAL_WARNING_DAYS
        ctx.update(self._layout())
        ctx["ncols"] = 7 + ctx["show_client"] + ctx["show_seizure"] + ctx["show_reason"]
        counts = tab_counts(self._scoped_base())
        ctx["tabs"] = [(key, label, counts[key]) for key, label, _ in TABS]
        for case in ctx["cases"]:
            case.creditors = side_names(case, "creditor")
            case.debtors = side_names(case, "debtor")
            case.closing_reason_uyap = uyap_closing_reason(case)
            if ctx["show_seizure"]:
                case.seizure_badges = seizure_types.kind_badges(case.seizures.all())
        return ctx
