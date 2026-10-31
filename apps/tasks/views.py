from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.cases.models import Case
from apps.core.text import fold
from apps.office.models import TaskType

from . import services
from .forms import CommentForm, TaskForm
from .models import OPEN_STATUSES, Task, TaskStatus

SCOPES = {
    "bana": "Bana atanan",
    "kontrol": "Kontrolümde",
    "olusturdugum": "Oluşturduklarım",
    "tumu": "Tümü",
}


def task_queryset():
    return Task.objects.select_related("task_type", "case", "client", "assignee", "reviewer")


class TaskListView(ListView):
    template_name = "tasks/list.html"
    context_object_name = "tasks"

    def get_paginate_by(self, queryset):
        return self.request.user.page_size

    def get_queryset(self):
        g, u = self.request.GET, self.request.user
        qs = task_queryset()
        scope = g.get("kapsam", "bana")
        if scope == "bana":
            qs = qs.filter(assignee=u)
        elif scope == "kontrol":
            qs = qs.filter(reviewer=u)
        elif scope == "olusturdugum":
            qs = qs.filter(created_by=u)
        status = g.get("durum", "acik")
        if status == "acik":
            qs = qs.filter(status__in=OPEN_STATUSES)
        elif status in TaskStatus.values:
            qs = qs.filter(status=status)
        if t := g.get("tur"):
            qs = qs.filter(task_type_id=t)
        if q := g.get("q", "").strip():
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(case__archive_no__icontains=q)
                | Q(case__subject__icontains=q)
                | Q(client__search_key__contains=fold(q))
            )
        return qs.order_by("due_date", "pk")

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["tasks/_list_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        u = self.request.user
        counts = {
            "bana": Task.objects.filter(assignee=u, status__in=OPEN_STATUSES).count(),
            "kontrol": Task.objects.filter(reviewer=u, status=TaskStatus.REVIEW).count(),
        }
        ctx.update(
            scopes=[(k, label, counts.get(k, 0)) for k, label in SCOPES.items()],
            scope=self.request.GET.get("kapsam", "bana"),
            statuses=TaskStatus.choices,
            types=TaskType.objects.filter(is_active=True),
        )
        return ctx


class TaskCreateView(CreateView):
    model = Task
    form_class = TaskForm
    template_name = "tasks/form.html"

    def get_initial(self):
        initial = {}
        case = Case.objects.filter(pk=self.request.GET.get("dosya")).first()
        if case:
            initial.update(
                case=case,
                client=case.client_id,
                assignee=case.responsible_intern_id,
                reviewer=case.responsible_lawyer_id,
            )
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        services.on_created(self.object, self.request.user)
        messages.success(self.request, "Görev oluşturuldu.")
        return response


class TaskUpdateView(UpdateView):
    model = Task
    form_class = TaskForm
    template_name = "tasks/form.html"

    def get_object(self, queryset=None):
        task = super().get_object(queryset)
        if not services.can_edit(task, self.request.user):
            raise PermissionDenied
        return task

    def form_valid(self, form):
        old_assignee = Task.objects.values_list("assignee_id", flat=True).get(pk=self.object.pk)
        changed = [form.fields[f].label for f in form.changed_data if f != "client"]
        response = super().form_valid(form)
        services.on_updated(self.object, self.request.user, changed, old_assignee)
        messages.success(self.request, "Görev güncellendi.")
        return response


class TaskDetailView(DetailView):
    template_name = "tasks/detail.html"
    context_object_name = "task"

    def get_queryset(self):
        return task_queryset()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        t, u = self.object, self.request.user
        ctx.update(
            actions=services.available_actions(t, u),
            can_edit=services.can_edit(t, u),
            events=t.events.select_related("actor"),
            comment_form=CommentForm(),
        )
        return ctx


class TaskActionView(View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        try:
            services.perform(
                task, request.POST.get("action", ""), request.user, request.POST.get("comment", "")
            )
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            messages.success(request, f"Görev durumu: {task.get_status_display()}")
        return redirect(task)


class TaskCommentView(View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        try:
            services.add_comment(task, request.user, request.POST.get("comment", ""))
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        return redirect(f"{task.get_absolute_url()}#gecmis")


def case_options(request):
    """Görev formunda müvekkile göre dosya listesi ve dosya seçilince varsayılanlar."""
    qs = Case.objects.select_related("client").order_by("-created_at")
    if client := request.GET.get("client"):
        qs = qs.filter(client_id=client)
    if not request.GET.get("all"):
        qs = qs.exclude(status="closed")
    return JsonResponse(
        {
            "cases": [
                {
                    "id": c.pk,
                    "label": f"{c.archive_no} — {c.subject} ({c.client})",
                    "client": c.client_id,
                    "lawyer": c.responsible_lawyer_id,
                    "intern": c.responsible_intern_id,
                }
                for c in qs[:500]
            ]
        }
    )
