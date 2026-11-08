"""Rutin görev kurallarının yönetimi (yönetici ve kıdemli avukat)."""

from django import forms
from django.contrib import messages
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import CreateView, ListView, UpdateView, View

from apps.core.permissions import RoutineManagerMixin

from .forms import TaskForm
from .models import RoutineDocument, RoutineTask, TaskEvent, TaskStatus
from .routines import routine_task_type


class RoutineForm(TaskForm):
    """Normal görev formunun aynısı; son gün yerine tekrar zamanı sorulur."""

    keep_notes_and_documents = True
    case_required = False  # rutin görev dosyasız (ofis içi) açılabilir

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
            "requires_document",
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
        # Rutin görevin türü her zaman "Rutin Görev"dir ve değiştirilemez.
        routine_type = routine_task_type()
        self.fields["task_type"].disabled = True
        self.fields["task_type"].required = False
        self.initial["task_type"] = routine_type.pk
        if not self.instance.pk:
            self.initial["requires_accounting"] = (
                "yes" if routine_type.requires_accounting else "no"
            )
            self.initial["requires_document"] = "yes" if routine_type.requires_document else "no"
        if self.instance.pk:
            self.initial["weekday"] = (
                "" if self.instance.weekday is None else str(self.instance.weekday)
            )
            self.fields["remove_documents"].queryset = self.instance.documents.all()

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
        self.instance.task_type = routine_task_type()
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


def routine_history(routine, limit=100):
    """Kuraldan açılan görevler: durum, tamamlanma, sonuç notu ve gelir/gider kaydı."""
    tasks = list(
        routine.tasks.select_related("assignee", "reviewer")
        .prefetch_related("events__actor")
        .order_by("-routine_date", "-pk")[:limit]
    )
    rows = []
    for task in tasks:
        events = list(task.events.all())
        closed = next((e for e in events if e.kind == TaskEvent.Kind.CLOSED), None)
        ledger = next(
            (
                e
                for e in events
                if e.kind == TaskEvent.Kind.NOTE and e.comment.startswith("Gelir/gider kaydı:")
            ),
            None,
        )
        rows.append({"task": task, "closed": closed, "ledger": ledger})
    summary = routine.tasks.aggregate(
        opened=Count("pk"),
        done=Count("pk", filter=Q(status=TaskStatus.DONE)),
        last_done=Max("completed_at"),
    )
    return {"rows": rows, "summary": summary}


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
        return RoutineTask.objects.select_related("assignee", "reviewer").annotate(
            opened_count=Count("tasks"),
            done_count=Count("tasks", filter=Q(tasks__status=TaskStatus.DONE)),
            last_done=Max("tasks__completed_at"),
        )


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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["history"] = routine_history(self.object)
        return ctx

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
