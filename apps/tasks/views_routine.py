"""Rutin görev kurallarının yönetimi (yalnızca yönetici)."""

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View

from apps.accounts.models import User
from apps.core.forms import BootstrapMixin
from apps.core.permissions import AdminRequiredMixin

from .models import RoutineTask


class RoutineForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = RoutineTask
        fields = [
            "title",
            "assignee",
            "reviewer",
            "frequency",
            "weekday",
            "month_day",
            "due_days",
            "is_active",
        ]

    weekday = forms.TypedChoiceField(
        label="Haftanın günü",
        choices=[("", "Seçiniz…"), *[(str(i), n) for i, n in RoutineTask.WEEKDAYS]],
        coerce=int,
        required=False,
    )
    month_day = forms.IntegerField(
        label="Ayın günü", min_value=1, max_value=31, required=False,
        help_text="31 gibi günler kısa aylarda ayın son gününe kayar.",
    )  # fmt: skip

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        users = User.objects.filter(is_active=True)
        self.fields["assignee"].queryset = users
        self.fields["reviewer"].queryset = users
        self.fields["reviewer"].empty_label = "Kontrolcü yok"
        if self.instance.pk:
            self.initial["weekday"] = (
                "" if self.instance.weekday is None else str(self.instance.weekday)
            )

    def clean(self):
        data = super().clean()
        if data.get("frequency") == RoutineTask.Frequency.WEEKLY:
            if data.get("weekday") in (None, ""):
                self.add_error("weekday", "Haftanın gününü seçin.")
            data["month_day"] = None
        elif data.get("frequency") == RoutineTask.Frequency.MONTHLY:
            if not data.get("month_day"):
                self.add_error("month_day", "Ayın gününü girin.")
            data["weekday"] = None
        a, r = data.get("assignee"), data.get("reviewer")
        if a and r and a == r:
            self.add_error("reviewer", "Kontrolcü, sorumludan farklı biri olmalı.")
        return data


class RoutineListView(AdminRequiredMixin, ListView):
    model = RoutineTask
    template_name = "tasks/routines.html"
    context_object_name = "routines"

    def get_queryset(self):
        return RoutineTask.objects.select_related("assignee", "reviewer")


class RoutineCreateView(AdminRequiredMixin, CreateView):
    model = RoutineTask
    form_class = RoutineForm
    template_name = "tasks/routine_form.html"
    success_url = reverse_lazy("tasks:routines")

    def get_initial(self):
        return {"is_active": True}

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Rutin görev kaydedildi.")
        return super().form_valid(form)


class RoutineUpdateView(AdminRequiredMixin, UpdateView):
    model = RoutineTask
    form_class = RoutineForm
    template_name = "tasks/routine_form.html"
    success_url = reverse_lazy("tasks:routines")

    def form_valid(self, form):
        messages.success(self.request, "Rutin görev güncellendi.")
        return super().form_valid(form)


class RoutineDeleteView(AdminRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        get_object_or_404(RoutineTask, pk=pk).delete()
        messages.success(request, "Rutin görev silindi; açılmış görevler korunur.")
        return redirect("tasks:routines")
