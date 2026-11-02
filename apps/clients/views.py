from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.db.models import (
    Count,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.accounting.models import BALANCE_EXPR, ZERO, LedgerEntry
from apps.accounting.permissions import can_view_balances
from apps.accounts.models import User
from apps.cases.flows import cluster
from apps.cases.models import Case
from apps.core.permissions import AdminRequiredMixin, is_admin
from apps.core.text import fold

from .forms import CLIENT_SUBRECORDS, DEFAULT_CONTACT_KINDS, ClientForm, client_formset
from .models import Client, PersonKind, PowerOfAttorney
from .services import delete_client, deletion_summary

# Sıralama seçenekleri (açılır listede görünenler). Sütun başlıkları da aynı anahtarları kullanır.
SORT_OPTIONS = {
    "-poa": "Vekalet no (yeniden eskiye)",
    "poa": "Vekalet no (eskiden yeniye)",
    "-created_at": "Kayıt tarihi (yeniden eskiye)",
    "created_at": "Kayıt tarihi (eskiden yeniye)",
    "name": "Ad (A–Z)",
    "-name": "Ad (Z–A)",
    "-case_count": "Dosya sayısı (çoktan aza)",
    "-open_task_count": "Açık görev (çoktan aza)",
    "-balance": "Bakiye (yüksekten düşüğe)",
}
SORT_FIELDS = {
    "poa",
    "created_at",
    "name",
    "case_count",
    "open_task_count",
    "balance",
    "responsible_lawyer__first_name",
}
DEFAULT_SORT = "-poa"


def client_ordering(sort: str) -> list:
    """Vekalet numarasına göre sıralamada numarası olmayanlar sona, kendi aralarında kayıt
    tarihine göre dizilir."""
    desc = sort.startswith("-")
    field = sort.lstrip("-")
    if field == "poa":
        poa = F("poa_no").desc(nulls_last=True) if desc else F("poa_no").asc(nulls_last=True)
        return [poa, "-created_at" if desc else "created_at", "pk"]
    return [sort, "pk"]


def annotate_list_values(qs):
    """Liste satırları: dosya sayısı, açık görev sayısı, bakiye (alt sorgularla)."""
    from apps.imports.models import PowerOfAttorneyReview, PowerOfAttorneyReviewMember
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
        .annotate(b=Sum(BALANCE_EXPR))
        .values("b")
    )
    money = DecimalField(max_digits=16, decimal_places=2)
    return qs.annotate(
        case_count=Count("cases", distinct=True),
        has_poa=Q(poa_no__isnull=False)
        | Exists(PowerOfAttorney.objects.filter(client=OuterRef("pk")))
        | Exists(
            PowerOfAttorneyReview.objects.filter(
                client=OuterRef("pk"), source_reference__iregex=r"^V\s*-\s*0*[1-9][0-9]{0,9}\s*$"
            )
        )
        | Exists(
            PowerOfAttorneyReviewMember.objects.filter(
                client=OuterRef("pk"),
                review__source_reference__iregex=r"^V\s*-\s*0*[1-9][0-9]{0,9}\s*$",
            )
        ),
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
            Client.objects.select_related(
                "responsible_lawyer", "responsible_intern"
            ).prefetch_related("imported_poa_rows", "imported_poa_members__review")
        )
        show_balance = can_view_balances(self.request.user)
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
        sort = g.get("sort") or DEFAULT_SORT
        if sort.lstrip("-") not in SORT_FIELDS or (
            sort.lstrip("-") == "balance" and not show_balance
        ):
            sort = DEFAULT_SORT
        self.sort = sort
        return qs.order_by(*client_ordering(sort))

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["clients/_list_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lawyers"] = User.objects.filter(role__in=["admin", "lawyer"], is_active=True)
        ctx["interns"] = User.objects.filter(role="intern", is_active=True)
        ctx["kinds"] = PersonKind.choices
        show_balance = can_view_balances(self.request.user)
        ctx["sort"] = self.sort
        ctx["sort_options"] = [
            (k, label) for k, label in SORT_OPTIONS.items() if show_balance or "balance" not in k
        ]
        return ctx


def client_reports(user, client) -> list[dict]:
    """Müvekkil detayındaki Raporlar sekmesi: müvekkile göre süzülmüş hazır raporlar."""

    from apps.reports.views import visible_reports

    params = {
        "cari-ekstre": {"client": client.pk},
        "dosya-son-durum": {"client": client.pk, "include_closed": "on"},
    }
    reports = []
    for key, spec in visible_reports(user).items():
        if key not in params:
            continue
        url = reverse("reports:report", args=[key]) + "?" + urlencode(params[key])
        reports.append({**spec, "url": url})
    return reports


def intern_by_lawyer() -> dict:
    """Avukat → bağlı stajyer eşlemesi (formda avukat seçilince stajyeri doldurmak için)."""
    mapping = {}
    for intern in User.objects.filter(
        role=User.Role.INTERN, is_active=True, supervisor__isnull=False
    ).order_by("order", "pk"):
        mapping.setdefault(intern.supervisor_id, intern.pk)
    return mapping


class ClientFormMixin:
    model = Client
    form_class = ClientForm
    template_name = "clients/form.html"

    def get_formsets(self):
        data = (self.request.POST, self.request.FILES) if self.request.method == "POST" else ()
        instance = self.object or Client()
        can_delete = is_admin(self.request.user)
        formsets = {}
        for prefix in CLIENT_SUBRECORDS:
            extra, initial = (0 if prefix == "sozlesme" else 1), None
            if prefix == "iletisim":
                # Telefon, e-posta ve adres için eksik türlerin boş satırı hazır gelir.
                have = (
                    set(instance.contacts.values_list("kind", flat=True)) if instance.pk else set()
                )
                initial = [{"kind": k} for k in DEFAULT_CONTACT_KINDS if k not in have]
                extra = len(initial)
            formset = client_formset(prefix, can_delete, extra)(
                *data, instance=instance, prefix=prefix, initial=initial
            )
            formsets[prefix] = (formset, "")
        return formsets

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("formsets", self.get_formsets())
        ctx["intern_by_lawyer"] = intern_by_lawyer()
        return ctx

    def form_valid(self, form):
        formsets = self.get_formsets()
        obj = form.instance
        # Yetkili yalnızca tüzel kişide; gerçek kişide o grup doğrulanmaz ve kaydedilmez.
        active = {
            prefix: value
            for prefix, value in formsets.items()
            if prefix != "yetkili" or obj.kind == PersonKind.COMPANY
        }
        if not all(fs.is_valid() for fs, _ in active.values()):
            return self.render_to_response(self.get_context_data(form=form, formsets=formsets))
        if not obj.pk:
            obj.created_by = self.request.user
        warnings = []
        fee_suggestions = []
        new_retainers = set()
        with transaction.atomic():
            self.object = form.save()
            for prefix, (fs, _) in active.items():
                fs.instance = self.object
                items = fs.save(commit=False)
                if prefix == "sozlesme":
                    new_retainers = {id(item) for item in items if not item.pk}
                for item in fs.deleted_objects:
                    item.delete()
                for item in items:
                    if hasattr(item, "created_by_id") and not item.pk:
                        item.created_by = self.request.user
                    item.save()
                    if getattr(item, "is_primary", False):
                        # Birincil kayıt tek olur (iletişimde her tür için ayrı).
                        same = {"kind": item.kind} if prefix == "iletisim" else {}
                        type(item).objects.filter(client=self.object, **same).exclude(
                            pk=item.pk
                        ).update(is_primary=False)
                    if prefix == "vekalet":
                        from apps.cases.documents import mirror_poa

                        if warning := mirror_poa(item):
                            warnings.append(warning)
                    if prefix == "sozlesme":
                        from apps.cases.documents import mirror_retainer

                        if warning := mirror_retainer(item):
                            warnings.append(warning)
                        if id(item) in new_retainers and item.fee_amount:
                            fee_suggestions.append(item)
            # Vekaleti olan müvekkile numara verilmemişse sıradaki V-numarası atanır.
            if not self.object.poa_no and self.object.powers_of_attorney.exists():
                locked = Client.objects.select_for_update().get(pk=self.object.pk)
                from apps.office.models import OfficeSettings

                OfficeSettings.load()
                OfficeSettings.objects.select_for_update().get(pk=1)
                locked.poa_no = Client.suggest_poa_no()
                locked.save(update_fields=["poa_no"])
                self.object.poa_no = locked.poa_no
        messages.success(self.request, "Müvekkil kaydedildi.")
        for warning in warnings:
            messages.warning(self.request, warning)
        if fee_suggestions:
            # Ücretli yeni sözleşme için vekalet ücretini muhasebeye kaydetme önerisi sunulur;
            # kullanıcı Vazgeç diyerek müvekkil sayfasına dönebilir.
            item = fee_suggestions[0]
            messages.info(
                self.request,
                "Avukatlık sözleşmesi kaydedildi. Vekalet ücreti muhasebeye henüz kaydedilmedi; "
                "aşağıdaki formla kaydedebilir veya Vazgeç diyebilirsiniz.",
            )
            query = urlencode(
                {
                    "tur": "fee",
                    "musteri": self.object.pk,
                    "dosya": item.case_id or "",
                    "tutar": f"{item.fee_amount:.2f}",
                    "aciklama": "Avukatlık sözleşmesi vekalet ücreti",
                    "next": self.object.get_absolute_url() + "#muhasebe",
                }
            )
            return redirect(f"{reverse('accounting:create')}?{query}")
        return redirect(self.object)


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
        return Client.objects.select_related(
            "responsible_lawyer", "responsible_intern"
        ).prefetch_related(
            "imported_poa_rows", "imported_poa_members__review", "powers_of_attorney"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.object
        ctx["cases"] = (
            Case.objects.filter(Q(client=c) | Q(co_clients=c))
            .distinct()
            .select_related("responsible_lawyer")
            .order_by("-created_at")
        )
        from apps.activity.views import history_for

        ctx["history"] = history_for(c)
        # Muhasebe sekmesi herkese açık; bakiye ve yürüyen bakiye yalnızca yetkiliye.
        from apps.accounting.views import statement

        entries = c.ledger_entries.select_related("case", "cancelled_by")
        # İptal edilen hareketler Muhasebe sekmesinde değil, Geçmiş sekmesinde görünür.
        ctx["ledger_rows"] = statement(entries.filter(is_cancelled=False))
        ctx["cancelled_entries"] = entries.filter(is_cancelled=True).order_by("-cancelled_at")
        if can_view_balances(self.request.user):
            ctx["ledger_balances"] = entries.balances()
        ctx["open_case_count"] = sum(1 for k in ctx["cases"] if k.is_open)
        ctx["closed_case_count"] = len(ctx["cases"]) - ctx["open_case_count"]
        ctx["client_reports"] = client_reports(self.request.user, c)
        ctx.update(case_filter_context(c, {}))
        return ctx


# Müvekkil detayındaki Dosyalar sekmesi: süzgeç ve sıralama
CASE_SORTS = {
    "-created_at": "Açılış (yeniden eskiye)",
    "created_at": "Açılış (eskiden yeniye)",
    "-archive_no": "Arşiv no (büyükten küçüğe)",
    "archive_no": "Arşiv no (küçükten büyüğe)",
    "subject": "Konu (A–Z)",
    "status": "Durum",
}


def client_cases(client, params):
    from apps.cases.models import Case, CaseStatus, CaseType

    qs = (
        Case.objects.filter(Q(client=client) | Q(co_clients=client))
        .distinct()
        .select_related("responsible_lawyer")
    )
    if q := params.get("q", "").strip():
        qs = qs.filter(
            Q(archive_no__unaccent__icontains=q)
            | Q(archive_folder_no__unaccent__icontains=q)
            | Q(official_no__unaccent__icontains=q)
            | Q(subject__unaccent__icontains=q)
            | Q(authority__unaccent__icontains=q)
        )
    if (case_type := params.get("type")) in CaseType.values:
        qs = qs.filter(case_type=case_type)
    status = params.get("status", "")
    if status == "open":
        qs = qs.exclude(status=CaseStatus.CLOSED)
    elif status in CaseStatus.values:
        qs = qs.filter(status=status)
    sort = params.get("sort") or "-created_at"
    if sort not in CASE_SORTS:
        sort = "-created_at"
    return qs.order_by(sort, "-pk"), sort


def case_filter_context(client, params) -> dict:
    from apps.cases.models import CaseStatus, CaseType

    cases, sort = client_cases(client, params)
    return {
        "client": client,
        "client_cases": cluster(cases),
        "case_sort": sort,
        "case_sorts": CASE_SORTS.items(),
        "case_types": CaseType.choices,
        "case_statuses": CaseStatus.choices,
    }


class ClientCasesView(View):
    """Dosyalar sekmesinin HTMX ile yenilenen tablosu."""

    def get(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        return render(
            request, "clients/_cases_table.html", case_filter_context(client, request.GET)
        )


class ClientDeleteView(AdminRequiredMixin, View):
    """Onay sayfası: birlikte silinecek kayıtlar sayılarıyla gösterilir, onay kutusu istenir."""

    template_name = "clients/confirm_delete.html"

    def get(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        return render(
            request, self.template_name, {"client": client, "summary": deletion_summary(client)}
        )

    def post(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        if not request.POST.get("confirm"):
            messages.error(request, "Silmek için onay kutusunu işaretleyin.")
            return redirect("clients:delete", pk=pk)
        name = str(client)
        delete_client(client)
        messages.success(request, f"{name} ve bağlı kayıtları silindi.")
        return redirect("clients:list")


def client_defaults(request, pk):
    """Dosya formunda müvekkil seçilince sorumluları doldurmak için."""
    c = get_object_or_404(Client, pk=pk)
    return JsonResponse(
        {
            "client_id": c.pk,
            "responsible_lawyer": c.responsible_lawyer_id,
            "responsible_intern": c.responsible_intern_id,
        }
    )
