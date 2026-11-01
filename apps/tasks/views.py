from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.cases.models import Case
from apps.core.permissions import is_admin
from apps.core.text import fold
from apps.core.uploads import validate_upload
from apps.office.models import TaskType

from . import services
from .forms import CommentForm, TaskForm
from .models import OPEN_STATUSES, Task, TaskDocument, TaskEvent, TaskStatus

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
                | Q(case__archive_folder_no__icontains=q)
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
        with transaction.atomic():
            form.instance.case = Case.objects.select_for_update().get(pk=form.instance.case_id)
            response = super().form_valid(form)
            services.on_created(self.object, self.request.user)
        messages.success(self.request, "Görev oluşturuldu.")
        return response


class TaskUpdateView(UpdateView):
    model = Task
    form_class = TaskForm
    template_name = "tasks/form.html"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.select_for_update() if self.request.method == "POST" else qs

    def get_object(self, queryset=None):
        task = super().get_object(queryset)
        if not services.can_edit(task, self.request.user):
            raise PermissionDenied
        return task

    def form_valid(self, form):
        form.instance.case = Case.objects.select_for_update().get(pk=form.instance.case_id)
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
        if t.assignee_id == u.pk and not t.assignee_seen:
            # Sorumlu yeni görevi açtı; ana sayfadaki "Yeni görev" uyarısı kalkar.
            Task.objects.filter(pk=t.pk).update(assignee_seen=True)
        ctx.update(
            actions=services.available_actions(t, u),
            can_edit=services.can_edit(t, u),
            can_delete=services.can_delete(t, u),
            **documents_context(t, u),
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
            for w in getattr(task, "warnings", []):
                messages.warning(request, w)
        return redirect(task)


class TaskDeleteView(View):
    """Yanlış açılan görevi oluşturan veya yönetici siler (aktivite kaydına düşer)."""

    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        if not services.can_delete(task, request.user):
            raise PermissionDenied
        case = task.case
        task.delete()
        messages.success(request, "Görev silindi.")
        return redirect(case)


class TaskCommentView(View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        try:
            services.add_comment(task, request.user, request.POST.get("comment", ""))
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        return redirect(f"{task.get_absolute_url()}#gecmis")


def case_options(request):
    """Görev ve muhasebe formlarında dosya seçimi yardımcısı.

    ?id=<dosya>      : tek dosyanın müvekkil ve sorumluları (seçim sonrası doldurma)
    ?client=<müvekkil>: o müvekkilin bütün dosyaları (sınır yok)
    Müvekkil seçilmemişken liste sunucunun çizdiği tam seçenek listesinden geri yüklenir.
    """
    qs = Case.objects.select_related("client").order_by("-created_at")
    if case_id := request.GET.get("id"):
        qs = qs.filter(pk=case_id if case_id.isdigit() else 0)
    elif client := request.GET.get("client"):
        cid = client if client.isdigit() else 0
        qs = qs.filter(Q(client_id=cid) | Q(co_clients=cid)).distinct()
    else:
        qs = qs.none()
    if not request.GET.get("all"):
        qs = qs.exclude(status="closed")
    return JsonResponse(
        {
            "cases": [
                {
                    "id": c.pk,
                    "label": f"{c.archive_reference} — {c.display_name} ({c.client})",
                    "client": c.client_id,
                    "lawyer": c.responsible_lawyer_id,
                    "intern": c.responsible_intern_id,
                }
                for c in qs
            ]
        }
    )


def documents_context(task, user, error=""):
    docs = list(task.documents.select_related("uploaded_by").order_by("-created_at"))
    current = [d for d in docs if d.is_current]
    return {
        "task_docs": current,
        "old_docs": {
            d.pk: [o for o in docs if not o.is_current and _root(o, docs) == d.pk] for d in current
        },
        "can_upload": services.can_upload(task, user),
        "doc_error": error,
    }


def _root(doc, docs):
    """Bir eski sürümün hangi güncel belgeye ait olduğunu bulur (sürüm zinciri)."""
    by_prev = {d.previous_id: d for d in docs if d.previous_id}
    while doc.pk in by_prev:
        doc = by_prev[doc.pk]
    return doc.pk


def _docs_partial(request, task, error=""):
    return render(
        request,
        "tasks/_documents.html",
        {"task": task, **documents_context(task, request.user, error)},
    )


class TaskDocumentUploadView(View):
    @transaction.atomic
    def post(self, request, pk):
        task = get_object_or_404(Task.objects.select_for_update(), pk=pk)
        if not services.can_upload(task, request.user):
            raise PermissionDenied
        f = request.FILES.get("file")
        if not f:
            return _docs_partial(request, task, "Yüklenecek belgeyi seçin.")
        try:
            validate_upload(f)
        except ValidationError as e:
            return _docs_partial(request, task, " ".join(e.messages))
        previous = task.documents.filter(
            pk=request.POST.get("replaces") or 0, is_current=True
        ).first()
        doc = TaskDocument(
            task=task,
            original_name=f.name[:300],
            size=f.size,
            uploaded_by=request.user,
            previous=previous,
            version=(previous.version + 1) if previous else 1,
        )
        doc.file.save(f.name, f, save=False)
        doc.save()
        if previous:
            previous.is_current = False
            previous.save(update_fields=["is_current"])
        verb = f"yeni sürüm yükledi (v{doc.version})" if previous else "belge yükledi"
        TaskEvent.objects.create(
            task=task, actor=request.user, kind="updated", comment=f"{doc.original_name} — {verb}"
        )
        return _docs_partial(request, task)


class TaskDocumentDeleteView(View):
    """Aktif görevde belgeyi yükleyen veya yönetici siler; önceki sürüm varsa o güncel olur."""

    @transaction.atomic
    def post(self, request, pk, doc_pk):
        task = get_object_or_404(Task.objects.select_for_update(), pk=pk)
        doc = get_object_or_404(TaskDocument, pk=doc_pk, task=task, is_current=True)
        if task.status != TaskStatus.ACTIVE or not (
            doc.uploaded_by_id == request.user.pk or is_admin(request.user)
        ):
            raise PermissionDenied
        previous = doc.previous
        doc.file.delete(save=False)
        doc.delete()
        if previous:
            previous.is_current = True
            previous.save(update_fields=["is_current"])
        return _docs_partial(request, task)
