"""Ofis içi gelir/gider (müvekkile bağlı olmayan büro kayıtları): yalnızca yönetici."""

import datetime as dt
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import CreateView, ListView, View

from apps.core.forms import BootstrapMixin, DateInput
from apps.core.pagination import page_size
from apps.core.permissions import AdminRequiredMixin
from apps.core.uploads import PDF_OR_IMAGE, validate_upload

from .models import OfficeEntry

ZERO = Decimal("0.00")


class OfficeEntryForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = OfficeEntry
        fields = ["kind", "amount", "date", "description", "receipt", "receipt_no"]
        widgets = {"kind": forms.RadioSelect, "date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].widget.attrs.update({"class": "form-check-input"})
        self.fields["amount"].widget.attrs.update(
            {"step": "0.01", "min": "0.01", "inputmode": "decimal"}
        )

    def clean_receipt(self):
        f = self.cleaned_data.get("receipt")
        validate_upload(f, PDF_OR_IMAGE, 20 * 1024 * 1024)
        return f

    def clean(self):
        data = super().clean()
        if data.get("kind") != OfficeEntry.Kind.EXPENSE:
            data["receipt_no"] = ""  # makbuz numarası yalnızca giderlerde tutulur
        return data


def _date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


class OfficeEntryListView(AdminRequiredMixin, ListView):
    template_name = "accounting/office_list.html"
    context_object_name = "entries"

    def get_paginate_by(self, queryset):
        return page_size(self.request)

    def period(self):
        g = self.request.GET
        today = timezone.localdate()
        if g.get("baslangic") or g.get("bitis"):
            return _date(g.get("baslangic")), _date(g.get("bitis"))
        return today.replace(day=1), None  # varsayılan: bu ayın başından bugüne

    def filtered(self):
        g = self.request.GET
        qs = OfficeEntry.objects.select_related("created_by", "cancelled_by")
        start, end = self.period()
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        if (kind := g.get("tur")) in OfficeEntry.Kind.values:
            qs = qs.filter(kind=kind)
        if q := g.get("q", "").strip():
            qs = qs.filter(description__icontains=q)
        return qs

    def get_queryset(self):
        return self.filtered().order_by("-date", "-pk")

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["accounting/_office_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        active = self.filtered().filter(is_cancelled=False)

        def total(kind):
            return active.filter(kind=kind).aggregate(t=Sum("amount"))["t"] or ZERO

        income, expense = total(OfficeEntry.Kind.INCOME), total(OfficeEntry.Kind.EXPENSE)
        start, end = self.period()
        ctx.update(
            income=income,
            expense=expense,
            net=income - expense,
            kinds=OfficeEntry.Kind.choices,
            start=start,
            end=end,
        )
        return ctx


@method_decorator(xframe_options_sameorigin, name="dispatch")
class OfficeEntryCreateView(AdminRequiredMixin, CreateView):
    model = OfficeEntry
    form_class = OfficeEntryForm
    template_name = "accounting/office_form.html"
    success_url = reverse_lazy("accounting:office_list")

    def get_initial(self):
        return {"date": timezone.localdate(), "kind": OfficeEntry.Kind.EXPENSE}

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        super().form_valid(form)
        messages.success(self.request, f"{self.object.get_kind_display()} kaydedildi.")
        if self.request.GET.get("pencere"):
            return HttpResponse("<script>window.parent.location.reload()</script>")
        return redirect(self.success_url)


class OfficeEntryCancelView(AdminRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        entry = get_object_or_404(OfficeEntry, pk=pk)
        reason = request.POST.get("reason", "").strip()
        if entry.is_cancelled:
            messages.error(request, "Bu hareket daha önce iptal edilmiş.")
        elif not reason:
            messages.error(request, "İptal nedeni yazılmalı.")
        else:
            entry.is_cancelled = True
            entry.cancelled_at = timezone.now()
            entry.cancelled_by = request.user
            entry.cancel_reason = reason[:300]
            entry.save(
                update_fields=[
                    "is_cancelled",
                    "cancelled_at",
                    "cancelled_by",
                    "cancel_reason",
                    "updated_at",
                ]
            )
            messages.success(request, "Hareket iptal edildi.")
        return redirect("accounting:office_list")
