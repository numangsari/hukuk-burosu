import datetime as dt

from django.contrib import messages
from django.core.exceptions import ValidationError
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
from apps.core.pagination import page_size
from apps.core.text import fold

from .forms import LedgerEntryForm
from .models import KIND_HELP, EntryKind, LedgerEntry
from .permissions import EditRequiredMixin, ViewRequiredMixin
from .services import cancel_entry, create_entry

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


class EntryListView(ViewRequiredMixin, ListView):
    template_name = "accounting/list.html"
    context_object_name = "entries"

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
