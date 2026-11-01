from django.contrib import messages
from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, ProtectedError, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.accounting.permissions import can_view as can_view_accounting
from apps.accounting.views import statement
from apps.accounts.models import User
from apps.clients.models import Client, Party
from apps.core.permissions import AdminRequiredMixin, is_admin
from apps.core.text import fold
from apps.office.models import Court

from . import services, stages, summary
from .documents import mirror_document
from .forms import (
    CaseCloseForm,
    CaseEventForm,
    CaseForm,
    CasePartyForm,
    CaseStageForm,
    CaseStepForm,
    DocumentForm,
    HearingForm,
    PartyFormSet,
)
from .models import TYPE_LABELS, Case, CaseParty, CaseStatus, CaseStep, CaseType, Document
from .party_roles import PARTY_ROLES, party_lanes

SORT_FIELDS = {
    "archive_no",
    "subject",
    "client__name",
    "case_type",
    "status",
    "created_at",
    "opened_on",
    "open_task_count",
}


class CaseListView(ListView):
    model = Case
    template_name = "cases/list.html"
    context_object_name = "cases"

    def get_paginate_by(self, queryset):
        return self.request.user.page_size

    def get_queryset(self):
        g = self.request.GET
        from apps.tasks.models import OPEN_STATUSES, Task

        open_tasks = (
            Task.objects.filter(case=OuterRef("pk"), status__in=OPEN_STATUSES)
            .order_by()
            .values("case")
            .annotate(n=Count("pk"))
            .values("n")
        )
        qs = Case.objects.select_related(
            "client", "responsible_lawyer", "responsible_intern"
        ).annotate(
            open_task_count=Coalesce(Subquery(open_tasks, output_field=IntegerField()), Value(0))
        )
        if q := g.get("q", "").strip():
            qs = qs.filter(
                Q(archive_no__icontains=q)
                | Q(archive_folder_no__icontains=q)
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
        ctx["party_roles"] = PARTY_ROLES
        ctx["party_lanes"] = party_lanes()
        if "party_formset" not in ctx:
            kind = (
                self.request.POST.get("case_type", "civil")
                if self.request.method == "POST"
                else ctx["form"]["case_type"].value() or "civil"
            )
            ctx["party_formset"] = PartyFormSet(
                self.request.POST if self.request.method == "POST" else None,
                prefix="parties",
                form_kwargs={"case_type": kind},
            )
        ctx["authorities"] = Court.objects.filter(is_active=True).values_list("name", flat=True)
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["can_remove_parties"] = self.request.user.is_office_admin
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        formset = self.get_context_data(form=form)["party_formset"]
        if not formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form, party_formset=formset))
        if not form.instance.pk:
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        for link, field in form.existing_party_rows:
            if form.cleaned_data.get(f"party_remove_{link.pk}"):
                link.delete()
                continue
            link.role = form.cleaned_data[field.name]
            link.save(update_fields=["role"])
        for row in formset:
            if not row.cleaned_data or row.cleaned_data.get("DELETE"):
                continue
            data = row.cleaned_data
            party = (
                Party.objects.filter(identity_no=data["identity_no"]).first()
                if data["identity_no"]
                else None
            )
            if party is None:
                party = row.save(commit=False)
                party.created_by = self.request.user
                party.save()
            CaseParty.objects.get_or_create(
                case=self.object, party=party, defaults={"role": data["role"]}
            )
        messages.success(self.request, "Dosya kaydedildi.")
        return response


class CaseCreateView(CaseFormMixin, CreateView):
    def get_initial(self):
        initial = {"case_type": CaseType.CIVIL}
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
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.select_for_update() if self.request.method == "POST" else qs


class CaseDetailView(DetailView):
    model = Case
    template_name = "cases/detail.html"
    context_object_name = "case"

    def get_queryset(self):
        return Case.objects.select_related("client", "responsible_lawyer", "responsible_intern")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["party_form"] = CasePartyForm(case_type=self.object.case_type)
        ctx["stage_form"] = CaseStageForm(case=self.object)
        steps = stages.open_stages(self.object.case_type)
        current = next((i for i, (key, _) in enumerate(steps) if key == self.object.stage), -1)
        ctx["stage_steps"] = [
            {
                "key": key,
                "label": label,
                "state": "current" if i == current else "done" if i < current else "todo",
            }
            for i, (key, label) in enumerate(steps)
        ]
        ctx["document_form"] = DocumentForm()
        ctx["party_links"] = self.object.party_links.select_related("party", "case")
        ctx["documents"] = self.object.documents.select_related("created_by")
        case = self.object
        ctx.update(
            hearing_form=HearingForm(initial={"authority": case.authority}),
            hearings=case.hearings.order_by("-starts_at"),
            event_form=CaseEventForm(initial={"date": timezone.localdate()}),
            timeline=case.events.select_related("created_by"),
            steps=case.steps.all(),
            tasks=case.tasks.select_related("task_type", "assignee", "reviewer").order_by(
                "status", "due_date"
            ),
            now=timezone.now(),
            today=timezone.localdate(),
        )
        ctx["summary"] = summary.build_summary(
            case,
            list(ctx["tasks"]),
            list(ctx["hearings"]),
            list(ctx["steps"]),
            list(ctx["documents"]),
            ctx["now"],
            ctx["today"],
        )
        ctx["party_groups"] = summary.party_groups(case, list(ctx["party_links"]))
        ctx["recent_events"] = list(ctx["timeline"][:5])
        from apps.activity.views import history_for

        ctx["history"] = history_for(case)
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


def _parties_partial(request, case, form=None):
    return render(
        request,
        "cases/_parties.html",
        {
            "case": case,
            "party_form": form or CasePartyForm(case_type=case.case_type),
            "party_links": case.party_links.select_related("party"),
        },
    )


class CasePartyAddView(View):
    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        form = CasePartyForm(request.POST, case_type=case.case_type)
        if not form.is_valid():
            return _parties_partial(request, case, form)
        data = form.cleaned_data
        party = None
        if data["identity_no"]:
            party = Party.objects.filter(identity_no=data["identity_no"]).first()
        if party is None:
            party = form.save(commit=False)
            party.created_by = request.user
            party.save()
        CaseParty.objects.get_or_create(case=case, party=party, defaults={"role": data["role"]})
        return _parties_partial(request, case)


class CasePartyRemoveView(AdminRequiredMixin, View):
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


class CaseStageView(View):
    """Açık dosyanın aşamasını değiştirir."""

    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        form = CaseStageForm(request.POST, case=case)
        if form.is_valid():
            try:
                services.change_stage(case, form.cleaned_data["stage"], request.user)
                messages.success(request, "Aşama güncellendi.")
            except services.StatusError as error:
                messages.error(request, str(error))
        else:
            messages.error(request, "Geçerli bir aşama seçin.")
        return redirect(case)


class CaseCloseView(View):
    template_name = "cases/close.html"

    def _render(self, request, case, form):
        return render(
            request,
            self.template_name,
            {"case": case, "form": form, "flags": form.flags, "has_decision": form.has_decision},
        )

    def get(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        if not case.is_open:
            messages.error(request, "Dosya zaten kapalı.")
            return redirect(case)
        return self._render(request, case, CaseCloseForm(case=case))

    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        form = CaseCloseForm(request.POST, case=case)
        if not form.is_valid():
            return self._render(request, case, form)
        try:
            closed = services.close_case(case, form.cleaned_data, request.user)
        except services.StatusError as error:
            messages.error(request, str(error))
            return redirect(case)
        messages.success(request, "Dosya kapatıldı.")
        if closed.closing_amount and not closed.closing_accounted:
            messages.warning(
                request,
                "Tahsil/ödeme tutarı muhasebeye kaydedilmedi. Dosya sayfasından muhasebe "
                "kaydını eklemeyi unutmayın.",
            )
        return redirect(closed)


class CaseReopenView(AdminRequiredMixin, View):
    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        form = CaseStageForm(request.POST, case=case)
        if form.is_valid():
            try:
                services.reopen_case(case, form.cleaned_data["stage"], request.user)
                messages.success(request, "Dosya yeniden açıldı.")
            except services.StatusError as error:
                messages.error(request, str(error))
        else:
            messages.error(request, "Geçerli bir aşama seçin.")
        return redirect(case)


class StepFormView(View):
    """Safahat adımı ekleme/düzenleme penceresi (HTMX); kayıttan sonra dosya sayfası yenilenir."""

    template_name = "cases/_step_form.html"

    def _render(self, request, case, form, step=None):
        return render(
            request,
            self.template_name,
            {
                "case": case,
                "form": form,
                "step": step,
                "authorities": Court.objects.filter(is_active=True).values_list("name", flat=True),
            },
        )

    def _objects(self, pk, step_pk):
        case = get_object_or_404(Case, pk=pk)
        if not case.has_safahat:
            raise Http404
        step = get_object_or_404(CaseStep, pk=step_pk, case=case) if step_pk else None
        return case, step

    def get(self, request, pk, step_pk=None):
        case, step = self._objects(pk, step_pk)
        return self._render(request, case, CaseStepForm(instance=step, case=case), step)

    def post(self, request, pk, step_pk=None):
        case, step = self._objects(pk, step_pk)
        form = CaseStepForm(request.POST, instance=step, case=case)
        if not form.is_valid():
            return self._render(request, case, form, step)
        with transaction.atomic():
            saved = form.save(commit=False)
            saved.case = case
            if not saved.pk:
                saved.created_by = request.user
            saved.save()
            if form.cleaned_data.get("apply_to_case"):
                services.apply_step_to_case(saved, request.user)
        messages.success(request, "Safahat adımı kaydedildi.")
        target = f"{case.get_absolute_url()}#t-safahat"
        if request.htmx:
            response = HttpResponse(status=204)
            response["HX-Redirect"] = target
            return response
        return redirect(target)


class StepApplyView(View):
    """Seçilen safahat adımının kurum ve dosya numarasını esas dosyaya yazar."""

    def post(self, request, pk, step_pk):
        case = get_object_or_404(Case, pk=pk)
        step = get_object_or_404(CaseStep, pk=step_pk, case=case)
        services.apply_step_to_case(step, request.user)
        messages.success(request, "Esas dosya bilgisi güncellendi.")
        return redirect(f"{case.get_absolute_url()}#t-safahat")


class StepDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk, step_pk):
        case = get_object_or_404(Case, pk=pk)
        get_object_or_404(CaseStep, pk=step_pk, case=case).delete()
        messages.success(request, "Safahat adımı silindi.")
        return redirect(f"{case.get_absolute_url()}#t-safahat")
