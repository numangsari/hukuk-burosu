from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, ProtectedError, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.accounting.models import LedgerEntry
from apps.accounting.permissions import can_view as can_view_accounting
from apps.accounting.views import statement
from apps.accounts.models import User
from apps.clients.models import Client, Party
from apps.core.pagination import page_size
from apps.core.permissions import AdminRequiredMixin, filter_visible_cases, is_admin
from apps.core.text import fold
from apps.office.models import Court

from . import flows, seizure_types, services, stages, summary
from .archive_locations import validate_archive_location
from .documents import mirror_document
from .forms import (
    CaseCloseForm,
    CaseEventForm,
    CaseForm,
    CaseLinkForm,
    CasePartyForm,
    CaseStageForm,
    CoClientFormSet,
    CollectionFormSet,
    DocumentForm,
    HearingForm,
    PartyFormSet,
)
from .models import (
    TYPE_LABELS,
    Case,
    CaseEvent,
    CaseParty,
    CaseStatus,
    CaseType,
    Document,
)
from .party_roles import PARTY_ROLES, party_lanes

SORT_FIELDS = {
    "archive_no",
    "subject",
    "client__name",
    "case_type",
    "status",
    "stage",
    "created_at",
    "opened_on",
    "open_task_count",
}


class CaseListView(ListView):
    model = Case
    template_name = "cases/list.html"
    context_object_name = "cases"

    def get_paginate_by(self, queryset):
        return page_size(self.request)

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
        base_qs = filter_visible_cases(
            Case.objects.select_related(
                "client", "responsible_lawyer", "responsible_intern", "portalcase"
            ).prefetch_related("co_clients"),
            self.request.user,
        )
        qs = base_qs.annotate(
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
                | Q(co_clients__search_key__contains=fold(q))
            ).distinct()
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
        if g.get("missing"):
            qs = qs.filter(
                Q(client__isnull=True)
                | Q(client_role="")
                | Q(archive_folder_no="")
                | Q(archive_no="")
                | Q(subject="")
            )
        if client := g.get("client"):
            qs = qs.filter(Q(client_id=client) | Q(co_clients=client)).distinct()
        selected = g.get("stage", "").split(":", 1)
        if len(selected) == 2 and selected[0] in CaseType.values:
            kind, key = selected
            if key in dict(stages.open_stages(kind)):
                qs = qs.filter(case_type=kind, stage=key, status=CaseStatus.OPEN)
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
        ctx["lawyers"] = User.objects.filter(role__in=["admin", "senior", "lawyer"], is_active=True)
        ctx["types"] = CaseType.choices
        ctx["statuses"] = CaseStatus.choices
        ctx["stage_groups"] = [
            (kind, label, stages.open_stages(kind)) for kind, label in CaseType.choices
        ]
        # Bağlı dosyalar sayfa içinde art arda ve bağ işaretiyle gösterilir.
        ctx["cases"] = ctx["object_list"] = flows.cluster(ctx["cases"])
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
        kind = (
            self.request.POST.get("case_type")
            or (self.object.case_type if getattr(self, "object", None) else None)
            or (ctx["form"]["case_type"].value() if "case_type" in ctx["form"].fields else None)
            or "civil"
        )
        if "party_formset" not in ctx:
            related = self._related_case()
            party_initial = None
            if related and self.request.method != "POST":
                # İlgili dosya oluştururken önceki dosyanın tarafları satır olarak gelir.
                party_initial = [
                    {
                        "role": link.role,
                        "kind": link.party.kind,
                        "name": link.party.name,
                        "identity_no": link.party.identity_no,
                        "lawyer": link.party.lawyer,
                        "address": link.party.address,
                        "existing_party": link.party_id,
                    }
                    for link in related.party_links.select_related("party")
                ]
            ctx["party_formset"] = PartyFormSet(
                self.request.POST if self.request.method == "POST" else None,
                prefix="parties",
                initial=party_initial,
                form_kwargs={"case_type": kind},
            )
        if "co_formset" not in ctx:
            instance = getattr(self, "object", None)
            related = self._related_case()
            source = instance if instance and instance.pk else related
            initial = (
                [
                    {"client": link.client_id, "role": link.role}
                    for link in source.co_client_links.all()
                ]
                if source and self.request.method != "POST"
                else None
            )
            ctx["co_formset"] = CoClientFormSet(
                self.request.POST if self.request.method == "POST" else None,
                prefix="coclients",
                initial=initial,
                form_kwargs={"case_type": kind},
            )
        ctx["authorities"] = Court.objects.filter(is_active=True).values_list("name", flat=True)
        ctx["related_case"] = self._related_case()
        return ctx

    def _related_case(self):
        """ "İlgili dosya oluştur" ile açılıyorsa bağlanacak dosya (aynı müvekkilin dosyası)."""
        raw = self.request.POST.get("related_case") or self.request.GET.get("iliskili")
        if not raw or getattr(self, "object", None) and self.object.pk:
            return None
        return (
            Case.objects.select_related("client").filter(pk=raw).first()
            if str(raw).isdigit()
            else None
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["can_remove_parties"] = self.request.user.is_office_admin
        kwargs["related_case"] = self._related_case_for_save() or self._related_case()
        kwargs["user"] = self.request.user
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        try:
            validate_archive_location(
                form.cleaned_data.get("archive_folder_no", ""),
                form.cleaned_data.get("archive_no", ""),
                form.instance,
                lock=True,
                client_id=form.cleaned_data["client"].pk if form.cleaned_data.get("client") else "",
            )
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field, message)
            return self.form_invalid(form)
        context = self.get_context_data(form=form)
        formset, co_formset = context["party_formset"], context["co_formset"]
        co_formset.primary_id = (
            form.cleaned_data["client"].pk if form.cleaned_data.get("client") else None
        )
        co_formset.case = form.instance if form.instance.pk else None
        if not (formset.is_valid() and co_formset.is_valid()):
            return self.render_to_response(
                self.get_context_data(form=form, party_formset=formset, co_formset=co_formset)
            )
        had_no_client = bool(
            form.instance.pk
            and Case.objects.filter(pk=form.instance.pk, client__isnull=True).exists()
        )
        if not form.instance.pk:
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        if had_no_client and self.object.client_id:
            from .documents import mirror_document

            for doc in self.object.documents.filter(is_current=True):
                if warning := mirror_document(doc):
                    messages.warning(self.request, warning)
                    break
        self._save_co_clients(co_formset)
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
            party = None
            if data.get("existing_party"):
                party = Party.objects.filter(pk=data["existing_party"]).first()
            if party is None and data["identity_no"]:
                party = Party.objects.filter(identity_no=data["identity_no"]).first()
            if party is None:
                party = row.save(commit=False)
                party.created_by = self.request.user
                party.save()
            CaseParty.objects.get_or_create(
                case=self.object, party=party, defaults={"role": data["role"]}
            )
        messages.success(self.request, "Dosya kaydedildi.")
        related = self._related_case_for_save()
        if related:
            try:
                services.link_cases(related, self.object, "", self.request.user)
                messages.success(
                    self.request, f"Dosya, {related.archive_reference} dosyasına bağlandı."
                )
            except services.StatusError as error:
                messages.warning(self.request, f"Dosya bağlanamadı: {error}")
        return response

    def _save_co_clients(self, co_formset):
        """Ek müvekkil satırlarını kayda eşitler (eklenen, değişen sıfat, çıkarılan)."""
        desired = {
            f.cleaned_data["client"].pk: f.cleaned_data["role"]
            for f in co_formset.forms
            if f.cleaned_data.get("client")
        }
        existing = {link.client_id: link for link in self.object.co_client_links.all()}
        for client_id, link in existing.items():
            if client_id not in desired:
                link.delete()
            elif link.role != desired[client_id]:
                link.role = desired[client_id]
                link.save(update_fields=["role"])
        for client_id, role in desired.items():
            if client_id not in existing:
                self.object.co_client_links.create(client_id=client_id, role=role)

    def _related_case_for_save(self):
        raw = self.request.POST.get("related_case")
        if not raw or not str(raw).isdigit():
            return None
        return Case.objects.filter(pk=raw).first()


@method_decorator(xframe_options_sameorigin, name="dispatch")
class CaseCreateView(CaseFormMixin, CreateView):
    def get_initial(self):
        initial = {"case_type": CaseType.CIVIL}
        client_id = self.request.GET.get("client")
        related = Case.objects.filter(pk=self.request.GET.get("iliskili") or 0).first()
        if related:
            # İlgili dosyanın klasörü önerilir; iç numara boş yerlerden ayrıca seçilir.
            client_id = related.client_id
            initial.update(
                subject=related.subject,
                client_role=related.client_role,
                archive_folder_no=related.archive_folder_no,
                archive_no="",
                responsible_lawyer=related.responsible_lawyer_id,
                responsible_intern=related.responsible_intern_id,
            )
        if (tur := self.request.GET.get("tur")) in CaseType.values:
            initial["case_type"] = tur
        if kurum := self.request.GET.get("kurum", "").strip():
            initial["authority"] = kurum
        if (yil := self.request.GET.get("yil", "").strip()).isdigit():
            initial["official_year"] = int(yil)
        if (numara := self.request.GET.get("numara", "").strip()).isdigit():
            initial["official_sequence"] = int(numara)
        record = self._source_record()
        if record:
            # Ofis listesi satırından açılıyorsa kaynak bilgiler önceden dolar.
            from apps.imports.office_sources import case_initial

            source = case_initial(record)
            source_client = source.pop("client", None)
            if source_client:
                client_id = source_client.pk
            initial.update(source)
        if client_id:
            client = Client.objects.filter(pk=client_id).first()
            if client:
                initial.setdefault("client", client)
                initial.setdefault("responsible_lawyer", client.responsible_lawyer_id)
                initial.setdefault("responsible_intern", client.responsible_intern_id)
        return initial

    def _source_record(self):
        """Yalnızca yöneticinin, henüz dosyaya bağlanmamış ofis listesi satırı."""
        from apps.imports.models import OfficeSourceRecord

        raw = self.request.POST.get("source_record") or self.request.GET.get("kaynak")
        if not self.request.user.is_office_admin or not str(raw or "").isdigit():
            return None
        return OfficeSourceRecord.objects.filter(pk=raw, case__isnull=True).first()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["source_record"] = self._source_record()
        return ctx

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            case = getattr(self, "object", None)
            record = self._source_record()
            if record and case and case.pk:
                from apps.imports.models import OfficeSourceRecord

                locked = OfficeSourceRecord.objects.select_for_update().get(pk=record.pk)
                if not locked.case_id:
                    locked.case, locked.reason = case, ""
                    locked.save(update_fields=["case", "reason"])
                    if record.sheet in ("KAPALI", "KAPALI1"):
                        case.status, case.stage = CaseStatus.CLOSED, ""
                        case.save(update_fields=["status", "stage"], preserve_unknown_stage=True)
                    messages.success(self.request, "Liste satırı bu dosyaya bağlandı.")
        if self.request.GET.get("pencere") and response.status_code == 302:
            return HttpResponse("<script>window.parent.location.reload()</script>")
        return response


class CaseUpdateView(CaseFormMixin, UpdateView):
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        qs = filter_visible_cases(super().get_queryset(), self.request.user)
        return qs.select_for_update(of=("self",)) if self.request.method == "POST" else qs


class CaseDetailView(DetailView):
    model = Case
    template_name = "cases/detail.html"
    context_object_name = "case"

    def get_queryset(self):
        return filter_visible_cases(
            Case.objects.select_related(
                "client", "responsible_lawyer", "responsible_intern", "portalcase"
            ),
            self.request.user,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.imports.portal_case_sync import missing_related_cases_for_view
        from apps.imports.portal_display import case_information

        ctx["portal_information"] = case_information(getattr(self.object, "portalcase", None))
        ctx["missing_related_cases"] = missing_related_cases_for_view(self.object)
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
        if self.object.case_type == CaseType.ENFORCEMENT:
            ctx["seizures"] = list(
                self.object.seizures.select_related(
                    "debtor_party", "debtor_client"
                ).prefetch_related("renewals__task")
            )
            ctx["seizure_groups"] = [
                {
                    "kind": kind,
                    "label": label,
                    "items": [s for s in ctx["seizures"] if s.kind == kind],
                }
                for kind, label in seizure_types.KINDS
            ]
            legacy = [s for s in ctx["seizures"] if not s.kind]
            if legacy:
                ctx["seizure_groups"].append(
                    {"kind": "", "label": "Önceki kayıtlar", "items": legacy}
                )
        ctx["document_form"] = DocumentForm()
        ctx["party_links"] = self.object.party_links.select_related("party", "case")
        ctx["documents"] = self.object.documents.select_related("created_by")
        ctx.update(_related_documents(self.object))
        case = self.object
        ctx.update(
            event_form=CaseEventForm(initial={"date": timezone.localdate()}),
            timeline=case.events.filter(kind=CaseEvent.Kind.NOTE).select_related("created_by"),
            flow_members=services.flow_members(case),
            can_unlink=can_unlink(self.request.user),
            tasks=case.tasks.select_related("task_type", "assignee", "reviewer").order_by(
                "status", "due_date"
            ),
            hearings=list(case.hearings.prefetch_related("tasks").order_by("-starts_at")),
            hearing_form=HearingForm(initial={"authority": case.authority}),
            now=timezone.now(),
            today=timezone.localdate(),
        )
        ctx["summary"] = summary.build_summary(
            case,
            list(ctx["tasks"]),
            list(ctx["flow_members"]),
            list(ctx["documents"]),
            ctx["today"],
        )
        additional = [*ctx["notice_documents"], *ctx["task_documents"]]
        ctx["summary"]["document_count"] += len(additional)
        dates = [d.created_at for d in additional]
        if ctx["summary"]["last_document_at"]:
            dates.append(ctx["summary"]["last_document_at"])
        ctx["summary"]["last_document_at"] = max(dates, default=None)
        ctx["party_groups"] = summary.party_groups(case, list(ctx["party_links"]))
        ctx["party_tab_groups"] = summary.party_groups(
            case, list(ctx["party_links"]), include_empty=True
        )
        from apps.activity.views import history_for

        ctx["history"] = history_for(case)
        if can_view_accounting(self.request.user):
            # Bağlı dosyalarda muhasebe ortaktır: gruptaki tüm dosyaların hareketleri görünür.
            entries = LedgerEntry.objects.filter(
                case_id__in=[m.pk for m in ctx["flow_members"]]
            ).select_related("cancelled_by", "case")
            # İptal edilen hareketler Muhasebe sekmesinde değil, Geçmiş sekmesinde görünür.
            ctx["multi_client"] = (
                len({cid for m in ctx["flow_members"] for cid in m.client_ids()}) > 1
            )
            ctx["ledger_rows"] = statement(entries.filter(is_cancelled=False))
            ctx["cancelled_entries"] = entries.filter(is_cancelled=True).order_by("-cancelled_at")
            ctx["ledger_balances"] = entries.balances()
        return ctx


class CaseDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        client = case.client
        flow_id = case.flow_id
        try:
            case.delete()
        except ProtectedError:
            messages.error(request, "Bu dosyaya bağlı kayıtlar var, silinemez.")
            return redirect(case)
        services.dissolve_if_single(flow_id)
        messages.success(request, "Dosya silindi.")
        return redirect(client) if client else redirect("cases:list")


def _parties_partial(request, case, form=None):
    return render(
        request,
        "cases/_parties.html",
        {
            "case": case,
            "party_form": form or CasePartyForm(case_type=case.case_type),
            "party_links": case.party_links.select_related("party"),
            "party_groups": summary.party_groups(
                case, list(case.party_links.select_related("party", "case")), include_empty=True
            ),
        },
    )


class CasePartyAddView(View):
    def post(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
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
        link = get_object_or_404(CaseParty, pk=link_pk, case=case)
        if not link.from_uyap:
            link.delete()
        return _parties_partial(request, case)


def _related_documents(case):
    from apps.imports.models import PortalNoticeDocument
    from apps.tasks.models import TaskDocument

    return {
        "notice_documents": list(
            PortalNoticeDocument.objects.filter(notice__resolution_case=case)
            .select_related("notice")
            .order_by("-created_at", "-pk")
        ),
        "task_documents": list(
            TaskDocument.objects.filter(task__case=case, is_current=True)
            .select_related("task", "uploaded_by")
            .order_by("-created_at", "-pk")
        ),
    }


def _documents_partial(request, case, form=None, warning=""):
    return render(
        request,
        "cases/_documents.html",
        {
            "case": case,
            "document_form": form or DocumentForm(),
            "documents": case.documents.select_related("created_by"),
            "folder_warning": warning,
            **_related_documents(case),
        },
    )


class DocumentUploadView(View):
    def post(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
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
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        doc = get_object_or_404(Document, pk=doc_pk, case=case)
        if doc.created_by_id == request.user.pk or is_admin(request.user):
            doc.file.delete(save=False)
            doc.delete()
        return _documents_partial(request, case)


class CaseStageView(View):
    """Açık dosyanın aşamasını değiştirir."""

    def post(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
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

    def _render(self, request, case, form, collections=None):
        return render(
            request,
            self.template_name,
            {
                "case": case,
                "form": form,
                "flags": form.flags,
                "has_decision": form.has_decision,
                "collections": collections
                if collections is not None
                else (CollectionFormSet(prefix="receipts") if form.is_enforcement else None),
                "previous_collections": case.ledger_entries.filter(closing_event__isnull=False),
            },
        )

    def get(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        if not case.is_open:
            messages.error(request, "Dosya zaten kapalı.")
            return redirect(case)
        return self._render(request, case, CaseCloseForm(case=case))

    def post(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        form = CaseCloseForm(request.POST, case=case)
        collections = (
            CollectionFormSet(request.POST, prefix="receipts") if form.is_enforcement else None
        )
        valid = form.is_valid()
        if collections is not None:
            valid = collections.is_valid() and valid
        if not valid:
            return self._render(request, case, form, collections)
        rows = (
            [
                row.cleaned_data
                for row in collections
                if row.cleaned_data and not row.cleaned_data.get("DELETE")
            ]
            if collections is not None
            else None
        )
        try:
            closed = services.close_case(case, form.cleaned_data, request.user, collections=rows)
        except services.StatusError as error:
            case.refresh_from_db()
            if not case.is_open:
                messages.info(request, "Dosya zaten kapalı; tahsilatlar tekrar kaydedilmedi.")
                return redirect(case)
            form.add_error(None, str(error))
            return self._render(request, case, form, collections)
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


def can_unlink(user) -> bool:
    """Bağlantıyı koparma yetkisi: yönetici ve avukatlar."""
    return user.is_authenticated and (
        is_admin(user) or user.role in (User.Role.SENIOR, User.Role.LAWYER)
    )


class LinkAddView(View):
    """İlgili dosya bağlama penceresi (HTMX): iki dosyanın safahatı ve muhasebesi ortak olur."""

    template_name = "cases/_link_form.html"

    def _render(self, request, case, form):
        return render(request, self.template_name, {"case": case, "form": form})

    def get(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        return self._render(request, case, CaseLinkForm(case=case))

    def post(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        form = CaseLinkForm(request.POST, case=case)
        if not form.is_valid():
            return self._render(request, case, form)
        try:
            services.link_cases(
                case, form.cleaned_data["related"], form.cleaned_data["note"], request.user
            )
        except services.StatusError as error:
            form.add_error(None, str(error))
            return self._render(request, case, form)
        messages.success(request, "Dosya bağlandı; safahat ve muhasebe ortak oldu.")
        if request.htmx:
            response = HttpResponse(status=204)
            response["HX-Trigger"] = "flow-saved"
            return response
        return redirect(f"{case.get_absolute_url()}#t-safahat")


def _flow_member(case, member_pk):
    members = services.flow_members(case)
    return get_object_or_404(Case, pk=member_pk, pk__in=[m.pk for m in members])


class LinkDeleteView(View):
    """Dosyanın bağlantısını koparır (yönetici ve avukatlar)."""

    def post(self, request, pk, member_pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        member = _flow_member(case, member_pk)
        if not can_unlink(request.user):
            raise PermissionDenied
        services.unlink_case(member, request.user)
        messages.success(request, "Bağlantı koparıldı.")
        return redirect(f"{case.get_absolute_url()}#t-safahat")


class LinkMoveView(View):
    """Dosyanın ortak akıştaki sırasını bir yukarı/aşağı değiştirir."""

    def post(self, request, pk, member_pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        member = _flow_member(case, member_pk)
        direction = request.POST.get("yon")
        if direction in ("up", "down") and services.move_member(member, direction):
            messages.success(request, "Akıştaki sıra değiştirildi.")
        return redirect(f"{case.get_absolute_url()}#t-safahat")
