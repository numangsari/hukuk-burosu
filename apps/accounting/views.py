import datetime as dt

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import CreateView, ListView, View

from apps.cases.models import Case
from apps.clients.models import Client
from apps.core.list_export import ListExportMixin
from apps.core.pagination import page_size
from apps.core.permissions import filter_visible_cases
from apps.core.text import fold, tr_title
from apps.reports.base import Column

from .forms import LedgerEntryForm
from .models import KIND_HELP, EntryKind, LedgerEntry
from .permissions import EditRequiredMixin, ViewRequiredMixin, can_exclude_portal
from .services import cancel_entry, create_entry, set_portal_exclusion

SORT_OPTIONS = [
    ("-date", "Tarih: yeniden eskiye"),
    ("date", "Tarih: eskiden yeniye"),
    ("-amount", "Tutar: büyükten küçüğe"),
    ("amount", "Tutar: küçükten büyüğe"),
    ("client__name", "Müvekkile göre"),
    ("-created_at", "Son kaydedilen"),
]


def _date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def statement(entries):
    """Tarih sırasıyla hareketler ve her satırdan sonraki bakiye (ekstre)."""
    balance = 0
    rows = []
    for e in sorted(entries, key=lambda x: (x.date, x.pk)):
        if not e.is_cancelled:
            balance += e.balance_effect
        rows.append({"entry": e, "balance": balance})
    rows.reverse()  # en yeni üstte
    return rows


class EntryListView(ListExportMixin, ViewRequiredMixin, ListView):
    template_name = "accounting/list.html"
    context_object_name = "entries"
    export_title = "Muhasebe Hareketleri"

    def export_columns(self):
        return [
            Column("Tarih", "date", 0.9),
            Column("Hareket", width=1.4),
            Column("Müvekkil", width=2.0),
            Column("Dosya", width=2.2),
            Column("Açıklama", width=3.0),
            Column("Tutar", "money", 1.2),
            Column("Durum", width=1.0),
        ]

    def export_row(self, entry):
        if entry.is_cancelled:
            state = "İptal"
        elif entry.excluded_from_balance:
            state = "Hesap dışı"
        else:
            state = "Geçerli"
        return [
            entry.date,
            entry.get_kind_display(),
            tr_title(entry.client),
            tr_title(entry.case.display_name) if entry.case_id else "",
            entry.description,
            entry.amount,
            state,
        ]

    def get_paginate_by(self, queryset):
        return page_size(self.request)

    def filtered(self):
        g = self.request.GET
        qs = LedgerEntry.objects.select_related("client", "case", "created_by", "cancelled_by")
        if (c := g.get("musteri", "")).isdecimal() and len(c) <= 18:
            qs = qs.filter(client_id=c)
        if (k := g.get("dosya", "")).isdecimal() and len(k) <= 18:
            qs = qs.filter(case_id=k)
        if (kind := g.get("tur")) in EntryKind.values:
            qs = qs.filter(kind=kind)
        if start := _date(g.get("baslangic")):
            qs = qs.filter(date__gte=start)
        if end := _date(g.get("bitis")):
            qs = qs.filter(date__lte=end)
        if q := g.get("q", "").strip():
            qs = qs.filter(
                Q(description__icontains=q)
                | Q(client__search_key__contains=fold(q))
                | Q(case__archive_no__icontains=q)
                | Q(case__archive_folder_no__icontains=q)
                | Q(case__authority__icontains=q)
                | Q(case__official_no__icontains=q)
                | Q(case__subject__icontains=q)
            )
        state = g.get("durum", "all" if g.get("iptal") else "active")
        if state == "cancelled":
            qs = qs.filter(is_cancelled=True)
        elif state != "all":
            qs = qs.filter(is_cancelled=False)
        return qs

    def get_queryset(self):
        sort = self.request.GET.get("sort", "-date")
        if sort not in dict(SORT_OPTIONS):
            sort = "-date"
        return self.filtered().order_by(sort, "-pk")

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["accounting/_list_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = self.filtered()
        ctx.update(
            totals=qs.totals_by_kind(),
            balances=qs.balances(),
            kinds=EntryKind.choices,
            clients=Client.objects.filter(ledger_entries__isnull=False).distinct(),
            cases=Case.objects.filter(ledger_entries__isnull=False)
            .select_related("client")
            .distinct(),
            sort_options=SORT_OPTIONS,
            sort=self.request.GET.get("sort")
            if self.request.GET.get("sort") in dict(SORT_OPTIONS)
            else "-date",
            record_state=self.request.GET.get(
                "durum", "all" if self.request.GET.get("iptal") else "active"
            ),
        )
        return ctx


@method_decorator(xframe_options_sameorigin, name="dispatch")
class EntryCreateView(EditRequiredMixin, CreateView):
    model = LedgerEntry
    form_class = LedgerEntryForm
    template_name = "accounting/form.html"

    def permission_object(self, request):
        data = request.POST if request.method == "POST" else request.GET
        case_id, client_id = data.get("case") or data.get("dosya"), data.get("client")
        if request.method != "POST":
            client_id = data.get("musteri")
        if str(case_id or "").isdecimal() and len(str(case_id)) <= 18:
            return Case.objects.select_related("client").filter(pk=case_id).first()
        if str(client_id or "").isdecimal() and len(str(client_id)) <= 18:
            return Client.objects.filter(pk=client_id).first()
        return None

    def get_initial(self):
        g = self.request.GET
        initial = {"date": timezone.localdate(), "kind": g.get("tur") or EntryKind.FEE}
        if g.get("tutar"):
            initial["amount"] = g["tutar"]
        if g.get("aciklama"):
            initial["description"] = g["aciklama"][:300]
        if case := Case.objects.filter(pk=g.get("dosya")).first():
            initial.update(case=case, client=case.client_id)
        elif client := Client.objects.filter(pk=g.get("musteri")).first():
            initial["client"] = client
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["kind_help"] = {str(k): v for k, v in KIND_HELP.items()}
        return ctx

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        try:
            self.object = create_entry(form.save(commit=False))
        except ValidationError as e:
            form.add_error(None, e)
            return self.form_invalid(form)
        messages.success(self.request, f"{self.object.get_kind_display()} kaydedildi.")
        if self.request.GET.get("pencere"):
            return HttpResponse("<script>window.parent.location.reload()</script>")
        return redirect(self.get_success_url())

    def get_success_url(self):
        nxt = self.request.POST.get("next", "")
        return (
            nxt
            if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts=set())
            else self.object.client.get_absolute_url() + "#muhasebe"
        )


class EntryCancelView(EditRequiredMixin, View):
    def permission_object(self, request):
        return (
            LedgerEntry.objects.select_related("case__client", "client")
            .filter(pk=self.kwargs.get("pk"))
            .first()
        )

    def post(self, request, pk):
        entry = get_object_or_404(LedgerEntry, pk=pk, is_cancelled=False)
        reason = request.POST.get("reason", "").strip()
        try:
            cancel_entry(entry, request.user, reason)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            messages.success(request, "Hareket iptal edildi.")
        nxt = request.POST.get("next", "")
        return redirect(
            nxt
            if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts=set())
            else "accounting:list"
        )


class EntryExcludeView(View):
    """UYAP'tan gelen hareketi bakiye dışında bırakır / geri alır (rol matrisinde yetki)."""

    def post(self, request, pk):
        visible = filter_visible_cases(Case.objects.all(), request.user)
        entry = get_object_or_404(
            LedgerEntry.objects.select_related("case__client", "client").filter(
                Q(case__isnull=True) | Q(case__in=visible)
            ),
            pk=pk,
            is_cancelled=False,
            portal_ref__isnull=False,
        )
        if not can_exclude_portal(request.user, entry):
            raise PermissionDenied
        exclude = request.POST.get("action") != "include"
        try:
            set_portal_exclusion(entry, request.user, exclude, request.POST.get("reason", ""))
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            messages.success(
                request, "Hareket hesap dışı bırakıldı." if exclude else "Hareket hesaba katıldı."
            )
        nxt = request.POST.get("next", "")
        return redirect(
            nxt
            if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts=set())
            else "accounting:list"
        )
