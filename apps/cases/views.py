from django.contrib import messages
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.accounting.permissions import can_view as can_view_accounting
from apps.accounting.views import statement
from apps.accounts.models import User
from apps.clients.conflicts import clients_matching
from apps.clients.models import Client, Party
from apps.core.permissions import AdminRequiredMixin, is_admin
from apps.core.text import fold
from apps.office.models import Court

from .documents import mirror_document
from .forms import (
    CaseEventForm,
    CaseForm,
    CasePartyForm,
    DocumentForm,
    HearingForm,
    ServiceForm,
)
from .models import TYPE_LABELS, Case, CaseParty, CaseStatus, CaseType, Document

SORT_FIELDS = {"archive_no", "subject", "client__name", "case_type", "status", "created_at"}


class CaseListView(ListView):
    model = Case
    template_name = "cases/list.html"
    context_object_name = "cases"

    def get_paginate_by(self, queryset):
        return self.request.user.page_size

    def get_queryset(self):
        g = self.request.GET
        qs = Case.objects.select_related("client", "responsible_lawyer", "responsible_intern")
        if q := g.get("q", "").strip():
            qs = qs.filter(
                Q(archive_no__icontains=q)
                | Q(official_no__icontains=q)
                | Q(subject__icontains=q)
                | Q(authority__icontains=q)
                | Q(client__search_key__contains=fold(q))
            )
        if (t := g.get("type")) in CaseType.values:
            qs = qs.filter(case_type=t)
        status = g.get("status", "open")
        if status == "open":
            qs = qs.exclude(status=CaseStatus.CLOSED)
        elif status in CaseStatus.values:
            qs = qs.filter(status=status)
        if lawyer := g.get("lawyer"):
            qs = qs.filter(responsible_lawyer_id=lawyer)
        if g.get("mine"):
            u = self.request.user
            qs = qs.filter(Q(responsible_lawyer=u) | Q(responsible_intern=u))
        if client := g.get("client"):
            qs = qs.filter(client_id=client)
        sort = g.get("sort", "-created_at")
        if sort.lstrip("-") not in SORT_FIELDS:
            sort = "-created_at"
        return qs.order_by(sort, "pk")

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["cases/_list_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lawyers"] = User.objects.filter(role__in=["admin", "lawyer"], is_active=True)
        ctx["types"] = CaseType.choices
        ctx["statuses"] = CaseStatus.choices
        return ctx


class CaseFormMixin:
    model = Case
    form_class = CaseForm
    template_name = "cases/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["type_labels"] = {str(k): v for k, v in TYPE_LABELS.items()}
        ctx["authorities"] = Court.objects.filter(is_active=True).values_list("name", flat=True)
        return ctx

    def form_valid(self, form):
        if not form.instance.pk:
            form.instance.created_by = self.request.user
        messages.success(self.request, "Dosya kaydedildi.")
        return super().form_valid(form)


class CaseCreateView(CaseFormMixin, CreateView):
    def get_initial(self):
        initial = {"archive_no": Case.suggest_archive_no(), "case_type": CaseType.CIVIL}
        if client_id := self.request.GET.get("client"):
            client = Client.objects.filter(pk=client_id).first()
            if client:
                initial.update(
                    client=client,
                    responsible_lawyer=client.responsible_lawyer_id,
                    responsible_intern=client.responsible_intern_id,
                )
        return initial


class CaseUpdateView(CaseFormMixin, UpdateView):
    pass


class CaseDetailView(DetailView):
    model = Case
    template_name = "cases/detail.html"
    context_object_name = "case"

    def get_queryset(self):
        return Case.objects.select_related("client", "responsible_lawyer", "responsible_intern")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["party_form"] = CasePartyForm()
        ctx["document_form"] = DocumentForm()
        ctx["party_links"] = self.object.party_links.select_related("party")
        ctx["documents"] = self.object.documents.select_related("created_by")
        case = self.object
        ctx.update(
            hearing_form=HearingForm(initial={"authority": case.authority}),
            hearings=case.hearings.order_by("-starts_at"),
            service_form=ServiceForm(initial={"served_on": timezone.localdate()}),
            services=case.services.all(),
            event_form=CaseEventForm(initial={"date": timezone.localdate()}),
            timeline=case.events.select_related("created_by"),
            tasks=case.tasks.select_related("task_type", "assignee", "reviewer").order_by(
                "status", "due_date"
            ),
            now=timezone.now(),
            today=timezone.localdate(),
        )
        if can_view_accounting(self.request.user):
            entries = case.ledger_entries.select_related("cancelled_by")
            ctx["ledger_rows"] = statement(entries)
            ctx["ledger_balances"] = entries.balances()
        return ctx


class CaseDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        client = case.client
        try:
            case.delete()
        except ProtectedError:
            messages.error(request, "Bu dosyaya bağlı kayıtlar var, silinemez.")
            return redirect(case)
        messages.success(request, "Dosya silindi.")
        return redirect(client)


def _parties_partial(request, case, form=None, conflicts=None):
    return render(
        request,
        "cases/_parties.html",
        {
            "case": case,
            "party_form": form or CasePartyForm(),
            "party_links": case.party_links.select_related("party"),
            "conflicts": conflicts or [],
        },
    )


class CasePartyAddView(View):
    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        form = CasePartyForm(request.POST)
        if not form.is_valid():
            return _parties_partial(request, case, form)
        data = form.cleaned_data
        conflicts = clients_matching(data["name"], data["identity_no"])
        if conflicts and not data.get("confirm_conflict"):
            form.add_error("confirm_conflict", "Eklemek için uyarıyı onaylayın.")
            return _parties_partial(request, case, form, conflicts)
        party = None
        if data["identity_no"]:
            party = Party.objects.filter(identity_no=data["identity_no"]).first()
        if party is None:
            party = form.save(commit=False)
            party.created_by = request.user
            party.save()
        CaseParty.objects.get_or_create(case=case, party=party, defaults={"role": data["role"]})
        return _parties_partial(request, case)


class CasePartyRemoveView(View):
    def post(self, request, pk, link_pk):
        case = get_object_or_404(Case, pk=pk)
        get_object_or_404(CaseParty, pk=link_pk, case=case).delete()
        return _parties_partial(request, case)


def _documents_partial(request, case, form=None, warning=""):
    return render(
        request,
        "cases/_documents.html",
        {
            "case": case,
            "document_form": form or DocumentForm(),
            "documents": case.documents.select_related("created_by"),
            "folder_warning": warning,
        },
    )


class DocumentUploadView(View):
    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        form = DocumentForm(request.POST, request.FILES)
        if not form.is_valid():
            return _documents_partial(request, case, form)
        doc = form.save(commit=False)
        doc.case = case
        doc.created_by = request.user
        doc.original_name = request.FILES["file"].name
        doc.save()
        return _documents_partial(request, case, warning=mirror_document(doc))


class DocumentDeleteView(View):
    """Belgeyi yalnızca yükleyen kişi veya yönetici silebilir."""

    def post(self, request, pk, doc_pk):
        case = get_object_or_404(Case, pk=pk)
        doc = get_object_or_404(Document, pk=doc_pk, case=case)
        if doc.created_by_id == request.user.pk or is_admin(request.user):
            doc.file.delete(save=False)
            doc.delete()
        return _documents_partial(request, case)
