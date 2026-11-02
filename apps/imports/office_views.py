import re

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.cases.models import Case, CaseType
from apps.clients.models import Client
from apps.core.permissions import AdminRequiredMixin

from . import office_sources
from .models import OfficeSourceRecord


class OfficeSourceListView(AdminRequiredMixin, View):
    def get(self, request):
        rows = OfficeSourceRecord.objects.filter(case__isnull=True, skipped=False)
        query = request.GET.get("q", "").strip()
        if query:
            rows = rows.filter(
                Q(source_name__icontains=query)
                | Q(reason__icontains=query)
                | Q(values__icontains=query)
            )
        page = Paginator(rows, 25).get_page(request.GET.get("page"))
        return render(request, "imports/office_review.html", {"page_obj": page, "query": query})


class CaseChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, case):
        return f"{case.client} — {case.display_name} — {case.archive_reference}"


class OfficeSourceDetailView(AdminRequiredMixin, View):
    def _form(self, data=None):
        field = CaseChoiceField(
            queryset=Case.objects.select_related("client").order_by("client__name", "authority"),
            label="Dosya",
            empty_label="Dosya seçin",
            widget=forms.Select(attrs={"class": "form-select", "data-searchable": "Dosya ara"}),
        )
        form = forms.Form(data)
        form.fields["case"] = field
        return form

    def get(self, request, pk):
        row = get_object_or_404(OfficeSourceRecord, pk=pk)
        return render(
            request, "imports/office_review_detail.html", {"row": row, "form": self._form()}
        )

    @transaction.atomic
    def post(self, request, pk):
        row = get_object_or_404(OfficeSourceRecord.objects.select_for_update(), pk=pk)
        form = self._form(request.POST)
        if row.case_id:
            messages.warning(request, "Bu satır daha önce bir dosyaya bağlanmış.")
            return redirect("imports:office_review_detail", pk=pk)
        if form.is_valid():
            row.case = form.cleaned_data["case"]
            row.reason = ""
            row.save(update_fields=["case", "reason"])
            messages.success(request, "Satır seçtiğiniz dosyaya bağlandı.")
            return redirect("imports:office_review")
        return render(request, "imports/office_review_detail.html", {"row": row, "form": form})


class OfficeBulkView(AdminRequiredMixin, View):
    """Bekleyen satırlar düz listede: müvekkil ve tür seçilir, dosya olarak kaydedilir."""

    per_page = 40

    def _queryset(self, params):
        status = params.get("durum", "pending")
        rows = OfficeSourceRecord.objects.filter(case__isnull=True, skipped=(status == "skipped"))
        query = params.get("q", "").strip()
        if query:
            rows = rows.filter(Q(values__icontains=query) | Q(reason__icontains=query))
        if params.get("neden"):
            rows = rows.filter(reason=params["neden"])
        if params.get("sayfa_adi"):
            rows = rows.filter(sheet=params["sayfa_adi"])
        return rows, status

    def _sources(self):
        try:
            _, rows = office_sources.read_sources()
        except (OSError, ValueError):
            return {}
        return {(r.source_hash, r.sheet, r.number): r for r in rows}

    @staticmethod
    def _client_text(client):
        return f"{client.name} [#{client.pk}]"

    def get(self, request):
        rows, status = self._queryset(request.GET)
        page = Paginator(rows, self.per_page).get_page(request.GET.get("page"))
        sources = self._sources()
        index = office_sources._client_index()
        items = []
        for record in page.object_list:
            row = sources.get((record.source_sha256, record.sheet, record.row_number))
            client = office_sources.suggest_client(row, index) if row else None
            case_type = ""
            if row:
                case_type = (
                    CaseType.ENFORCEMENT
                    if row.kind == "enforcement"
                    else office_sources.archive_type(row.authority) or ""
                )
            items.append(
                {
                    "record": record,
                    "row": row,
                    "client_text": self._client_text(client) if client else "",
                    "case_type": case_type,
                }
            )
        reasons = (
            OfficeSourceRecord.objects.filter(case__isnull=True)
            .exclude(reason="")
            .values_list("reason", flat=True)
            .distinct()
            .order_by("reason")
        )
        context = {
            "items": items,
            "page_obj": page,
            "status": status,
            "query": request.GET.get("q", ""),
            "reason": request.GET.get("neden", ""),
            "sheet": request.GET.get("sayfa_adi", ""),
            "reasons": list(reasons),
            "sheets": ["AÇIK", "KAPALI", "KAPALI1", "İCRA TAKİP LİSTESİ"],
            "clients": [
                (self._client_text(c), c.search_key) for c in Client.objects.order_by("search_key")
            ],
            "case_types": CaseType.choices,
            "querystring": request.GET.urlencode(),
        }
        return render(request, "imports/office_bulk.html", context)

    def _resolve_client(self, text, index):
        match = re.search(r"\[#(\d+)\]\s*$", text)
        if match:
            return (
                Client.objects.select_related("responsible_lawyer", "responsible_intern")
                .filter(pk=match.group(1))
                .first()
            )
        found = index.get(office_sources.key(text), [])
        return found[0] if len(found) == 1 else None

    def post(self, request):
        sources = self._sources()
        index = office_sources._client_index()
        done = {"created": 0, "linked": 0, "skipped": 0, "restored": 0}
        errors = []
        for raw in request.POST.getlist("rid"):
            if not raw.isdigit():
                continue
            pk = int(raw)
            label = f"{pk}. kayıt"
            try:
                with transaction.atomic():
                    record = OfficeSourceRecord.objects.select_for_update().filter(pk=pk).first()
                    if record is None or record.case_id:
                        continue
                    label = f"{record.sheet} {record.row_number}. satır"
                    if request.POST.get(f"skip_{pk}") and not record.skipped:
                        record.skipped = True
                        record.save(update_fields=["skipped"])
                        done["skipped"] += 1
                        continue
                    if request.POST.get(f"unskip_{pk}") and record.skipped:
                        record.skipped = False
                        record.save(update_fields=["skipped"])
                        done["restored"] += 1
                        continue
                    text = request.POST.get(f"client_{pk}", "").strip()
                    kind = request.POST.get(f"type_{pk}", "")
                    if not text and not kind:
                        continue
                    if not text or kind not in CaseType.values:
                        raise ValidationError("müvekkil ve tür birlikte seçilmeli")
                    client = self._resolve_client(text, index)
                    if client is None:
                        raise ValidationError("müvekkil listeden seçilmeli")
                    row = sources.get((record.source_sha256, record.sheet, record.row_number))
                    if row is None:
                        raise ValidationError("kaynak liste değişmiş")
                    case, outcome = office_sources.create_case(record, row, client, kind)
                    record.case, record.reason = case, ""
                    record.save(update_fields=["case", "reason"])
                    done[outcome] += 1
            except ValidationError as exc:
                errors.append(f"{label}: {exc.messages[0]}")
        names = (
            ("dosya açıldı", "created"),
            ("satır mevcut dosyaya bağlandı", "linked"),
            ("satır atlandı", "skipped"),
            ("satırın atlaması kaldırıldı", "restored"),
        )
        parts = [f"{done[key]} {name}" for name, key in names if done[key]]
        if parts:
            messages.success(request, "; ".join(parts) + ".")
        for error in errors[:15]:
            messages.warning(request, error)
        if len(errors) > 15:
            messages.warning(request, f"{len(errors) - 15} satır daha kaydedilemedi.")
        return redirect(f"{reverse('imports:office_bulk')}?{request.POST.get('querystring', '')}")
