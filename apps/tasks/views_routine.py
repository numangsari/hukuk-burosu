"""Rutin görev kurallarının yönetimi (yönetici ve kıdemli avukat)."""

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import CreateView, ListView, UpdateView, View

from apps.core.permissions import RoutineManagerMixin
from apps.office.models import TaskType

from .forms import TaskForm
from .models import RoutineDocument, RoutineTask
from .routines import ROUTINE_TYPE_NAME


class RoutineForm(TaskForm):
    """Normal görev formunun aynısı; son gün yerine tekrar zamanı sorulur."""

    keep_notes_and_documents = True

    class Meta:
        model = RoutineTask
        fields = [
            "task_type",
            "title",
            "case",
            "assignee",
            "reviewer",
            "second_reviewer",
            "requires_accounting",
            "notes",
            "frequency",
            "weekday",
            "month_day",
            "due_days",
            "is_active",
        ]
        labels = {"due_days": "Süre (gün)"}

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
    remove_documents = forms.ModelMultipleChoiceField(
        label="Kaldırılacak belgeler",
        queryset=RoutineDocument.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task_type"].required = True
        if self.instance.pk:
            self.initial["weekday"] = (
                "" if self.instance.weekday is None else str(self.instance.weekday)
            )
            self.fields["remove_documents"].queryset = self.instance.documents.all()
        else:
            routine_type = TaskType.objects.filter(name=ROUTINE_TYPE_NAME, is_active=True).first()
            if routine_type:
                self.initial.setdefault("task_type", routine_type.pk)

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
        return data

    def save(self, commit=True):
        routine = super().save(commit=commit)
        if commit:
            self.save_documents(routine)
        return routine

    def save_documents(self, routine):
        for doc in self.cleaned_data.get("remove_documents") or []:
            doc.file.delete(save=False)
            doc.delete()
        for f in self.cleaned_data.get("document") or []:
            RoutineDocument.objects.create(
                routine=routine, file=f, original_name=f.name[:300], size=f.size
            )


class RoutineFormMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class RoutineListView(RoutineManagerMixin, ListView):
    model = RoutineTask
    template_name = "tasks/routines.html"
    context_object_name = "routines"

    def get_queryset(self):
        return RoutineTask.objects.select_related("assignee", "reviewer")


@method_decorator(xframe_options_sameorigin, name="dispatch")
class RoutineCreateView(RoutineManagerMixin, RoutineFormMixin, CreateView):
    model = RoutineTask
    form_class = RoutineForm
    template_name = "tasks/routine_form.html"
    success_url = reverse_lazy("tasks:routines")

    def get_initial(self):
        return {"is_active": True}

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, "Rutin görev kaydedildi.")
        if self.request.GET.get("pencere"):
            return HttpResponse("<script>window.parent.location.reload()</script>")
        return response


@method_decorator(xframe_options_sameorigin, name="dispatch")
class RoutineUpdateView(RoutineManagerMixin, RoutineFormMixin, UpdateView):
    model = RoutineTask
    form_class = RoutineForm
    template_name = "tasks/routine_form.html"
    success_url = reverse_lazy("tasks:routines")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Rutin görev güncellendi.")
        if self.request.GET.get("pencere"):
            return HttpResponse("<script>window.parent.location.reload()</script>")
        return response


class RoutineDeleteView(RoutineManagerMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        get_object_or_404(RoutineTask, pk=pk).delete()
        messages.success(request, "Rutin görev silindi; açılmış görevler korunur.")
        return redirect("tasks:routines")
