from django.contrib import messages
from django.db.models import (
    Count,
    DecimalField,
    Exists,
    IntegerField,
    OuterRef,
    ProtectedError,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.accounting.models import CARI_EXPR, ZERO, LedgerEntry
from apps.accounting.permissions import can_view as can_view_accounting
from apps.accounts.models import User
from apps.core.permissions import AdminRequiredMixin
from apps.core.text import fold

from .conflicts import parties_matching
from .forms import SUBRECORDS, ClientForm
from .models import Client, PersonKind, PowerOfAttorney

SORT_FIELDS = {
    "name",
    "kind",
    "case_count",
    "open_task_count",
    "balance",
    "responsible_lawyer__first_name",
    "created_at",
}


def annotate_list_values(qs):
    """Liste satırları: dosya sayısı, açık görev sayısı, cari bakiye (alt sorgularla)."""
    from apps.tasks.models import OPEN_STATUSES, Task

    open_tasks = (
        Task.objects.filter(client=OuterRef("pk"), status__in=OPEN_STATUSES)
        .order_by()
        .values("client")
        .annotate(n=Count("pk"))
        .values("n")
    )
    balance = (
        LedgerEntry.objects.filter(client=OuterRef("pk"), is_cancelled=False)
        .order_by()
        .values("client")
        .annotate(b=Sum(CARI_EXPR))
        .values("b")
    )
    money = DecimalField(max_digits=16, decimal_places=2)
    return qs.annotate(
        case_count=Count("cases", distinct=True),
        has_poa=Exists(PowerOfAttorney.objects.filter(client=OuterRef("pk"))),
        open_task_count=Coalesce(Subquery(open_tasks, output_field=IntegerField()), Value(0)),
        balance=Coalesce(Subquery(balance, output_field=money), Value(ZERO), output_field=money),
    )


class ClientListView(ListView):
    model = Client
    template_name = "clients/list.html"
    context_object_name = "clients"

    def get_paginate_by(self, queryset):
        return self.request.user.page_size

    def get_queryset(self):
        g = self.request.GET
        qs = annotate_list_values(
            Client.objects.select_related("responsible_lawyer", "responsible_intern")
        )
        show_balance = can_view_accounting(self.request.user)
        if q := g.get("q", "").strip():
            key = fold(q)
            qs = qs.filter(Q(search_key__contains=key) | Q(tckn=q) | Q(vkn=q))
        if (kind := g.get("kind")) in PersonKind.values:
            qs = qs.filter(kind=kind)
        if g.get("poa") == "yes":
            qs = qs.filter(has_poa=True)
        elif g.get("poa") == "no":
            qs = qs.filter(has_poa=False)
        if lawyer := g.get("lawyer"):
            qs = qs.filter(responsible_lawyer_id=lawyer)
        if intern := g.get("intern"):
            qs = qs.filter(responsible_intern_id=intern)
        if g.get("tasks") == "yes":
            qs = qs.filter(open_task_count__gt=0)
        elif g.get("tasks") == "no":
            qs = qs.filter(open_task_count=0)
        if show_balance and g.get("debt") == "yes":
            qs = qs.filter(balance__gt=0)
        elif show_balance and g.get("debt") == "no":
            qs = qs.filter(balance__lte=0)
        active = g.get("active", "1")
        if active in ("0", "1"):
            qs = qs.filter(is_active=active == "1")
        sort = g.get("sort", "name")
        if sort.lstrip("-") not in SORT_FIELDS or (
            sort.lstrip("-") == "balance" and not show_balance
        ):
            sort = "name"
        return qs.order_by(sort, "pk")

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["clients/_list_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lawyers"] = User.objects.filter(role__in=["admin", "lawyer"], is_active=True)
        ctx["interns"] = User.objects.filter(role="intern", is_active=True)
        ctx["kinds"] = PersonKind.choices
        return ctx


class ClientFormMixin:
    model = Client
    form_class = ClientForm
    template_name = "clients/form.html"

    def form_valid(self, form):
        obj = form.instance
        name = f"{obj.first_name} {obj.last_name}" if obj.kind == PersonKind.PERSON else obj.title
        identity = obj.tckn if obj.kind == PersonKind.PERSON else obj.vkn
        identity_fields = {"kind", "first_name", "last_name", "title", "tckn", "vkn"}
        changed = not obj.pk or identity_fields & set(form.changed_data)
        conflicts = parties_matching(name, identity) if changed else []
        if conflicts and not form.cleaned_data.get("confirm_conflict"):
            form.conflicts = conflicts
            form.add_error("confirm_conflict", "Kaydetmek için uyarıyı onaylayın.")
            return self.form_invalid(form)
        if not obj.pk:
            obj.created_by = self.request.user
        messages.success(self.request, "Müvekkil kaydedildi.")
        return super().form_valid(form)


class ClientCreateView(ClientFormMixin, CreateView):
    def get_initial(self):
        return {"kind": PersonKind.PERSON}


class ClientUpdateView(ClientFormMixin, UpdateView):
    pass


class ClientDetailView(DetailView):
    model = Client
    template_name = "clients/detail.html"
    context_object_name = "client"

    def get_queryset(self):
        return Client.objects.select_related("responsible_lawyer", "responsible_intern")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.object
        ctx["cases"] = c.cases.select_related("responsible_lawyer").order_by("-created_at")
        ctx["subforms"] = {key: spec[0]() for key, spec in SUBRECORDS.items()}
        ctx["conflicts"] = parties_matching(c.name, c.identity_no)
        from apps.activity.views import history_for

        ctx["history"] = history_for(c)
        if can_view_accounting(self.request.user):
            from apps.accounting.views import statement

            entries = c.ledger_entries.select_related("case", "cancelled_by")
            ctx["ledger_rows"] = statement(entries)
            ctx["ledger_balances"] = entries.balances()
        return ctx


class ClientDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        try:
            client.delete()
        except ProtectedError:
            messages.error(request, "Bu müvekkile bağlı dosyalar var. Önce pasife alın.")
            return redirect(client)
        messages.success(request, "Müvekkil silindi.")
        return redirect("clients:list")


class SubrecordView(View):
    """Müvekkil detayında iletişim, IBAN, yetkili ve vekalet satırlarını ekler/siler (HTMX)."""

    def _spec(self, kind):
        if kind not in SUBRECORDS:
            raise Http404
        return SUBRECORDS[kind]

    def post(self, request, pk, kind):
        form_class, related, _ = self._spec(kind)
        client = get_object_or_404(Client, pk=pk)
        form = form_class(request.POST, request.FILES)
        warning = ""
        if form.is_valid():
            item = form.save(commit=False)
            item.client = client
            if hasattr(item, "created_by"):
                item.created_by = request.user
            item.save()
            if kind == "vekalet":
                from apps.cases.documents import mirror_poa

                warning = mirror_poa(item)
            if getattr(item, "is_primary", False):
                getattr(client, related).exclude(pk=item.pk).filter(
                    **({"kind": item.kind} if kind == "iletisim" else {})
                ).update(is_primary=False)
            form = form_class()
        return render(
            request,
            f"clients/_sub_{kind}.html",
            {
                "client": client,
                "form": form,
                "items": getattr(client, related).all(),
                "folder_warning": warning,
            },
        )


class SubrecordDeleteView(View):
    def post(self, request, pk, kind, item_pk):
        if kind not in SUBRECORDS:
            raise Http404
        form_class, related, _ = SUBRECORDS[kind]
        client = get_object_or_404(Client, pk=pk)
        get_object_or_404(getattr(client, related), pk=item_pk).delete()
        return render(
            request,
            f"clients/_sub_{kind}.html",
            {"client": client, "form": form_class(), "items": getattr(client, related).all()},
        )


def client_defaults(request, pk):
    """Dosya formunda müvekkil seçilince sorumluları doldurmak için."""
    c = get_object_or_404(Client, pk=pk)
    return JsonResponse(
        {
            "responsible_lawyer": c.responsible_lawyer_id,
            "responsible_intern": c.responsible_intern_id,
        }
    )


def conflict_check(request):
    """Müvekkil formunda ad/kimlik girilirken canlı çıkar çatışması uyarısı (HTMX)."""
    g = request.GET
    if g.get("kind") == PersonKind.COMPANY:
        name, identity = g.get("title", ""), g.get("vkn", "")
    else:
        name = f"{g.get('first_name', '')} {g.get('last_name', '')}".strip()
        identity = g.get("tckn", "")
    if len(name) < 3 and not identity:
        return HttpResponse("")
    return render(
        request, "clients/_conflicts.html", {"conflicts": parties_matching(name, identity)}
    )
