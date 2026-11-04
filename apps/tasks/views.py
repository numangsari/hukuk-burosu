import datetime as dt

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.accounts.models import User
from apps.cases.documents import mirror_task_document
from apps.cases.models import Case
from apps.core.pagination import page_size
from apps.core.permissions import is_admin
from apps.core.text import fold
from apps.core.uploads import validate_upload
from apps.office.models import TaskType

from . import services
from .forms import CommentForm, TaskForm
from .models import OPEN_STATUSES, Task, TaskDocument, TaskEvent, TaskStatus

SCOPES = {
    "bana": "Bana atanmış",
    "tumu": "Tümü",
}
TABS = {
    "aktif": "Aktif görevlerim",
    "bekleyen": "Kontrolümü bekleyenler",
    "kontrolde": "Kontrolde olanlar",
    "kapali": "Kapalı görevler",
}


SORT_OPTIONS = [
    ("due_date", "Son gün: en yakın"),
    ("-due_date", "Son gün: en uzak"),
    ("-created_at", "Yeni eklenen"),
    ("created_at", "Eski eklenen"),
    ("title", "Görev adına göre"),
    ("assignee__first_name", "Sorumluya göre"),
    ("reviewer__first_name", "Kontrolcüye göre"),
    ("task_type__name", "Görev türüne göre"),
]
DEADLINE_OPTIONS = [
    ("overdue", "Geciken"),
    ("today", "Bugün"),
    ("tomorrow", "Yarın"),
    ("soon", "2–3 gün kaldı"),
    ("week", "Önümüzdeki 7 gün"),
]


def task_queryset():
    return Task.objects.select_related("task_type", "case", "client", "assignee", "reviewer")


class TaskListView(ListView):
    template_name = "tasks/list.html"
    context_object_name = "tasks"

    def get_paginate_by(self, queryset):
        return page_size(self.request)

    def get_queryset(self, tab_override=None):
        g, u = self.request.GET, self.request.user
        qs = task_queryset()
        scope = g.get("kapsam", "bana")
        if scope not in SCOPES:
            scope = "bana"
        tab = tab_override or g.get("sekme", "aktif")
        if tab not in TABS:
            tab = "aktif"
        if scope == "bana":
            if tab == "bekleyen":
                qs = qs.filter(reviewer=u)
            elif tab in ("aktif", "kontrolde"):
                qs = qs.filter(assignee=u)
            else:
                qs = qs.filter(Q(assignee=u) | Q(reviewer=u))
        qs = qs.filter(
            status={
                "aktif": TaskStatus.ACTIVE,
                "bekleyen": TaskStatus.REVIEW,
                "kontrolde": TaskStatus.REVIEW,
                "kapali": TaskStatus.DONE,
            }[tab]
        )
        if (t := g.get("tur", "")).isdecimal() and len(t) <= 18:
            qs = qs.filter(task_type_id=t)
        for parameter, field in (("sorumlu", "assignee_id"), ("kontrolcu", "reviewer_id")):
            if (value := g.get(parameter, "")).isdecimal() and len(value) <= 18:
                qs = qs.filter(**{field: value})
        today = timezone.localdate()
        deadline = g.get("son_gun")
        if tab != "kapali" and deadline in dict(DEADLINE_OPTIONS):
            qs = qs.filter(status__in=OPEN_STATUSES)
            if deadline == "overdue":
                qs = qs.filter(due_date__lt=today)
            elif deadline == "today":
                qs = qs.filter(due_date=today)
            elif deadline == "tomorrow":
                qs = qs.filter(due_date=today + dt.timedelta(days=1))
            elif deadline == "soon":
                qs = qs.filter(
                    due_date__range=(today + dt.timedelta(days=2), today + dt.timedelta(days=3))
                )
            else:
                qs = qs.filter(due_date__gte=today, due_date__lt=today + dt.timedelta(days=7))
        if q := g.get("q", "").strip():
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(case__archive_no__icontains=q)
                | Q(case__archive_folder_no__icontains=q)
                | Q(case__subject__icontains=q)
                | Q(case__authority__icontains=q)
                | Q(case__official_no__icontains=q)
                | Q(client__search_key__contains=fold(q))
            )
        sort = g.get("sort", "due_date")
        if sort not in dict(SORT_OPTIONS):
            sort = "due_date"
        return qs.order_by(sort, "pk")

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["tasks/_list_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        scope = (
            self.request.GET.get("kapsam") if self.request.GET.get("kapsam") in SCOPES else "bana"
        )
        tab = self.request.GET.get("sekme") if self.request.GET.get("sekme") in TABS else "aktif"
        ctx.update(
            scopes=SCOPES.items(),
            scope=scope,
            tab=tab,
            tabs=[
                (
                    key,
                    (
                        "Aktif görevler"
                        if key == "aktif"
                        else "Kontrol bekleyenler"
                        if key == "bekleyen"
                        else label
                    )
                    if scope == "tumu"
                    else label,
                    self.get_queryset(tab_override=key).count(),
                )
                for key, label in TABS.items()
            ],
            people=User.objects.filter(is_active=True).order_by("first_name", "last_name"),
            deadline_options=DEADLINE_OPTIONS,
            sort_options=SORT_OPTIONS,
            sort=self.request.GET.get("sort")
            if self.request.GET.get("sort") in dict(SORT_OPTIONS)
            else "due_date",
            statuses=TaskStatus.choices,
            types=TaskType.objects.filter(is_active=True),
        )
        return ctx


@method_decorator(xframe_options_sameorigin, name="dispatch")
class TaskCreateView(CreateView):
    model = Task
    form_class = TaskForm
    template_name = "tasks/form.html"

    def get_initial(self):
        initial = {}
        case = (
            Case.objects.select_related("responsible_lawyer")
            .filter(pk=self.request.GET.get("dosya"))
            .first()
        )
        if case:
            assignee_id = case.responsible_intern_id or case.responsible_lawyer_id
            reviewer_id = case.responsible_lawyer_id
            if assignee_id and reviewer_id == assignee_id:
                reviewer_id = (
                    case.responsible_lawyer.supervisor_id
                    if case.responsible_lawyer
                    and case.responsible_lawyer.supervisor_id != assignee_id
                    else None
                )
            initial.update(
                case=case,
                client=case.client_id,
                assignee=assignee_id,
                reviewer=reviewer_id,
            )
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        with transaction.atomic():
            form.instance.case = Case.objects.select_for_update(of=("self",)).get(
                pk=form.instance.case_id
            )
            response = super().form_valid(form)
            services.on_created(self.object, self.request.user)
            if self.object.notes.strip():
                TaskEvent.objects.create(
                    task=self.object,
                    actor=self.request.user,
                    kind=TaskEvent.Kind.NOTE,
                    comment=self.object.notes.strip(),
                )
                self.object.notes = ""
                self.object.save(update_fields=["notes"])
            for document in form.cleaned_data.get("document", []):
                doc = TaskDocument.objects.create(
                    task=self.object,
                    kind=TaskDocument.Kind.SOURCE,
                    file=document,
                    original_name=document.name[:300],
                    size=document.size,
                    uploaded_by=self.request.user,
                )
                TaskEvent.objects.create(
                    task=self.object,
                    actor=self.request.user,
                    kind="updated",
                    comment=f"{doc.original_name} — belge yükledi",
                )

                def mirror_after_commit(doc=doc):
                    warning = mirror_task_document(doc)
                    if warning:
                        messages.warning(self.request, warning)

                transaction.on_commit(mirror_after_commit)
        messages.success(self.request, "Görev oluşturuldu.")
        if self.request.GET.get("pencere"):
            return HttpResponse("<script>window.parent.location.reload()</script>")
        return response


@method_decorator(xframe_options_sameorigin, name="dispatch")
class TaskUpdateView(UpdateView):
    model = Task
    form_class = TaskForm
    template_name = "tasks/form.html"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.select_for_update(of=("self",)) if self.request.method == "POST" else qs

    def get_object(self, queryset=None):
        task = super().get_object(queryset)
        if not services.can_edit(task, self.request.user):
            raise PermissionDenied
        return task

    def form_valid(self, form):
        form.instance.case = Case.objects.select_for_update(of=("self",)).get(
            pk=form.instance.case_id
        )
        old_assignee = Task.objects.values_list("assignee_id", flat=True).get(pk=self.object.pk)
        changed = [form.fields[f].label for f in form.changed_data if f != "client"]
        response = super().form_valid(form)
        services.on_updated(self.object, self.request.user, changed, old_assignee)
        messages.success(self.request, "Görev güncellendi.")
        if self.request.GET.get("pencere"):
            return redirect(self.object.get_absolute_url() + "?pencere=1")
        return response


@method_decorator(xframe_options_sameorigin, name="dispatch")
class TaskDetailView(DetailView):
    template_name = "tasks/detail.html"
    context_object_name = "task"

    def get_queryset(self):
        return task_queryset()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        t, u = self.object, self.request.user
        from apps.accounting.models import LedgerEntry

        requires_accounting = t.requires_accounting or bool(
            t.task_type and t.task_type.requires_accounting
        )
        ledger_entries = (
            LedgerEntry.objects.active()
            .filter(client_id=t.client_id)
            .filter(Q(case_id=t.case_id) | Q(case__isnull=True))
            if requires_accounting
            else LedgerEntry.objects.none()
        )
        if t.assignee_id == u.pk and not t.assignee_seen:
            # Sorumlu yeni görevi açtı; ana sayfadaki "Yeni görev" uyarısı kalkar.
            Task.objects.filter(pk=t.pk).update(assignee_seen=True)
            t.assignee_seen = True
        ctx.update(
            actions=services.available_actions(t, u),
            ledger_entries=ledger_entries,
            can_edit=services.can_edit(t, u),
            can_delete=services.can_delete(t, u),
            **documents_context(t, u),
            events=t.events.exclude(kind=TaskEvent.Kind.COMMENT).select_related("actor"),
            comments=t.events.filter(kind=TaskEvent.Kind.COMMENT).select_related("actor"),
            comment_form=CommentForm(),
            notes=t.events.filter(kind=TaskEvent.Kind.NOTE).select_related("actor"),
        )
        return ctx


class TaskActionView(View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        client_informed_raw = request.POST.get("client_informed")
        client_informed = None
        if client_informed_raw in ("true", "1", "yes"):
            client_informed = True
        elif client_informed_raw in ("false", "0", "no"):
            client_informed = False

        try:
            services.perform(
                task,
                request.POST.get("action", ""),
                request.user,
                request.POST.get("comment", ""),
                request.POST.get("ledger_id", ""),
                hearing_outcome=request.POST.get("hearing_outcome", ""),
                hearing_decisions=request.POST.get("hearing_decisions", ""),
                client_informed=client_informed,
                client_not_informed_reason=request.POST.get("client_not_informed_reason", ""),
            )
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            messages.success(request, f"Görev durumu: {task.get_status_display()}")
            for w in getattr(task, "warnings", []):
                messages.warning(request, w)
        return redirect(
            task.get_absolute_url() + ("?pencere=1" if request.GET.get("pencere") else "")
        )


class TaskNoteView(View):
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        content = request.POST.get("note", "").strip()
        if content:
            TaskEvent.objects.create(
                task=task, actor=request.user, kind=TaskEvent.Kind.NOTE, comment=content
            )
        return redirect(
            task.get_absolute_url() + ("?pencere=1" if request.GET.get("pencere") else "")
        )


@method_decorator(xframe_options_sameorigin, name="dispatch")
class TaskDeleteView(View):
    """Yanlış açılan görevi oluşturan veya yönetici siler (aktivite kaydına düşer)."""

    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk)
        if not services.can_delete(task, request.user):
            raise PermissionDenied
        case = task.case
        task.delete()
        messages.success(request, "Görev silindi.")
        if request.GET.get("pencere"):
            return HttpResponse("<script>window.parent.location.reload()</script>")
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
    if client_id := request.GET.get("client_info"):
        from apps.clients.models import Client

        client = Client.objects.filter(pk=client_id if client_id.isdigit() else 0).first()
        return JsonResponse(
            {"lawyer": client.responsible_lawyer_id, "intern": client.responsible_intern_id}
            if client
            else {}
        )
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


def documents_context(task, user, error="", warning=""):
    docs = list(task.documents.select_related("uploaded_by").order_by("-created_at"))
    current = [d for d in docs if d.is_current]
    return {
        "task_docs": current,
        "source_docs": [d for d in current if d.kind != TaskDocument.Kind.PETITION],
        "petition_docs": [d for d in current if d.kind == TaskDocument.Kind.PETITION],
        "old_docs": {
            d.pk: [o for o in docs if not o.is_current and _root(o, docs) == d.pk] for d in current
        },
        "can_upload": services.can_upload(task, user),
        "doc_error": error,
        "doc_warning": warning,
    }


def _root(doc, docs):
    """Bir eski sürümün hangi güncel belgeye ait olduğunu bulur (sürüm zinciri)."""
    by_prev = {d.previous_id: d for d in docs if d.previous_id}
    while doc.pk in by_prev:
        doc = by_prev[doc.pk]
    return doc.pk


def _docs_partial(request, task, error="", warning=""):
    return render(
        request,
        "tasks/_documents.html",
        {"task": task, **documents_context(task, request.user, error, warning)},
    )


class TaskDocumentUploadView(View):
    @transaction.atomic
    def post(self, request, pk):
        task = get_object_or_404(Task.objects.select_for_update(of=("self",)), pk=pk)
        if not services.can_upload(task, request.user):
            raise PermissionDenied
        files = request.FILES.getlist("file")
        if not files:
            return _docs_partial(request, task, "Yüklenecek belgeyi seçin.")
        try:
            for f in files:
                validate_upload(f)
        except ValidationError as e:
            return _docs_partial(request, task, " ".join(e.messages))
        previous = task.documents.filter(
            pk=request.POST.get("replaces") or 0, is_current=True, kind=TaskDocument.Kind.PETITION
        ).first()
        if request.POST.get("replaces") and not previous:
            raise PermissionDenied
        if previous and len(files) != 1:
            return _docs_partial(request, task, "Yeni sürüm için tek belge seçin.")
        warnings = []
        for f in files:
            doc = TaskDocument(
                task=task,
                kind=TaskDocument.Kind.PETITION,
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
                task=task,
                actor=request.user,
                kind="updated",
                comment=f"{doc.original_name} — {verb}",
            )
            if warning := mirror_task_document(doc):
                warnings.append(warning)
        return _docs_partial(request, task, warning=" ".join(warnings))


class TaskDocumentDeleteView(View):
    """Aktif görevde belgeyi yükleyen veya yönetici siler; önceki sürüm varsa o güncel olur."""

    @transaction.atomic
    def post(self, request, pk, doc_pk):
        task = get_object_or_404(Task.objects.select_for_update(of=("self",)), pk=pk)
        doc = get_object_or_404(TaskDocument, pk=doc_pk, task=task, is_current=True)
        if (
            doc.kind != TaskDocument.Kind.PETITION
            or task.status != TaskStatus.ACTIVE
            or not task.approval_seen
            or not (doc.uploaded_by_id == request.user.pk or is_admin(request.user))
        ):
            raise PermissionDenied
        previous = doc.previous
        doc.file.delete(save=False)
        doc.delete()
        if previous:
            previous.is_current = True
            previous.save(update_fields=["is_current"])
        return _docs_partial(request, task)


class PetitionTemplateDownloadView(View):
    def get(self, request, pk):
        from pathlib import Path

        from django.http import FileResponse, HttpResponseBadRequest, HttpResponseNotFound

        from apps.core import folders
        from apps.core.text import tr_capitalize_words, tr_lower

        from .petition_templates import client_name, fill_docx, fill_udf, party_name

        task = get_object_or_404(Task.objects.select_related("case", "client", "task_type"), pk=pk)
        name = task.task_type.petition_template
        root = folders.root()
        if not root or not name or Path(name).name != name:
            return HttpResponseNotFound("Bu görev türü için şablon bulunmuyor.")
        directory = root / "Şablon Dilekçeler"
        path = directory / name
        if directory.is_symlink() or path.is_symlink() or not path.is_file():
            return HttpResponseNotFound("Şablon dosyası bulunmuyor.")
        client = task.client
        case = task.case
        groups = {"plaintiff": [], "defendant": []}

        def add_client(person, role):
            if role not in groups:
                return
            identity = person.tckn if person.kind == "person" else person.vkn
            label = "TC" if person.kind == "person" else "VKN"
            name = client_name(person) + (f" ({label}: {identity})" if identity else "")
            address = (
                person.contacts.filter(kind="address")
                .order_by("-is_primary", "pk")
                .values_list("value", flat=True)
                .first()
                or ""
            )
            groups[role].append((name, address))

        role = case.client_role
        if task.task_type.name == "Dava Dilekçesi Hazırlama Ve Dava Açılışı":
            role = "plaintiff"
        add_client(client, role)
        for link in case.co_client_links.select_related("client"):
            add_client(link.client, link.role)
        for link in case.party_links.select_related("party"):
            if link.role in groups:
                party = link.party
                identity = party.identity_no
                identity_label = "TC" if party.kind == "person" else "VKN"
                name = party_name(party) + (f" ({identity_label}: {identity})" if identity else "")
                groups[link.role].append((name, party.address))

        def names(role):
            return ", ".join(name for name, _ in groups[role])

        def addresses(role):
            return "; ".join(address for _, address in groups[role] if address)

        values = {
            "davaci": names("plaintiff"),
            "davaci_adres": addresses("plaintiff"),
            "davali": names("defendant"),
            "davali_adres": addresses("defendant"),
            "mahkeme": case.authority,
            "dosya_no": case.official_no_display,
            "konu": case.subject,
        }
        try:
            required = (
                set()
                if task.task_type.name == "Dava Dilekçesi Hazırlama Ve Dava Açılışı"
                else {"mahkeme", "dosya_no"}
            )
            renderer = fill_udf if path.suffix.lower() == ".udf" else fill_docx
            data = renderer(path.read_bytes(), values, required=required)
        except (OSError, ValidationError) as exc:
            return HttpResponseBadRequest(
                "Şablon hazırlanamadı: "
                + (
                    " ".join(exc.messages)
                    if isinstance(exc, ValidationError)
                    else "Dosya okunamadı."
                )
            )
        import io

        title = task.task_type.name
        if title == "Dava Dilekçesi Hazırlama Ve Dava Açılışı":
            title = "Dava Dilekçesi"
        authority = tr_capitalize_words(tr_lower(case.authority))
        reference = " ".join(part for part in (authority, case.official_no_display) if part)
        filename = " - ".join(part for part in (client_name(client), title, reference) if part)
        filename = folders.sanitize(filename, max_len=220) + path.suffix.lower()
        return FileResponse(io.BytesIO(data), as_attachment=True, filename=filename)
