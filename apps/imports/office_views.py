from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.cases.models import Case
from apps.core.permissions import AdminRequiredMixin

from .models import OfficeSourceRecord


class OfficeSourceListView(AdminRequiredMixin, View):
    def get(self, request):
        rows = OfficeSourceRecord.objects.filter(case__isnull=True)
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
