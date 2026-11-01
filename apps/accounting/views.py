import datetime as dt

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import CreateView, ListView, View

from apps.cases.models import Case
from apps.clients.models import Client

from .forms import LedgerEntryForm
from .models import KIND_HELP, EntryKind, LedgerEntry
from .permissions import EditRequiredMixin, ViewRequiredMixin
from .services import cancel_entry, create_entry


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
        return self.request.user.page_size

    def filtered(self):
        g = self.request.GET
        qs = LedgerEntry.objects.select_related("client", "case", "created_by")
        if c := g.get("musteri"):
            qs = qs.filter(client_id=c)
        if k := g.get("dosya"):
            qs = qs.filter(case_id=k)
        if (kind := g.get("tur")) in EntryKind.values:
            qs = qs.filter(kind=kind)
        if start := _date(g.get("baslangic")):
            qs = qs.filter(date__gte=start)
        if end := _date(g.get("bitis")):
            qs = qs.filter(date__lte=end)
        if not g.get("iptal"):
            qs = qs.filter(is_cancelled=False)
        return qs

    def get_queryset(self):
        return self.filtered()

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
        )
        return ctx


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
        return redirect(self.get_success_url())

    def get_success_url(self):
        nxt = self.request.POST.get("next", "")
        return (
            nxt
            if nxt.startswith("/") and not nxt.startswith("//")
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
            nxt if nxt.startswith("/") and not nxt.startswith("//") else "accounting:list"
        )
