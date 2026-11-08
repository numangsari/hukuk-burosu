"""Duruşmalar: oluşturma, ayrıntı penceresi (yaklaşan: düzenle; yapılmış: sonuç, bilgilendirme,
görev oluşturma), silme ve dışa aktarım."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin

from apps.agenda.google_sync import delete_hearing_from_google, queue_hearing_google_sync
from apps.core.permissions import (
    PermissionRequiredMixin,
    filter_visible_cases,
    filter_visible_hearings,
)
from apps.core.text import tr_title
from apps.core.whatsapp import format_hearing_result_message

from .forms import HearingClientNoteForm, HearingResultForm, HearingStandaloneForm
from .hearing_list import list_context
from .models import Case, CaseEvent, Hearing, HearingInformMethod, HearingStatus


def _safe_next(request) -> str:
    """POST'taki `next` adresi yalnızca site içi göreli yolsa döner; değilse boş."""
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts=set()):
        return nxt
    return ""


def _visible_hearing(request, pk):
    return get_object_or_404(
        filter_visible_hearings(
            Hearing.objects.select_related("case", "case__client", "client", "assigned_to"),
            request.user,
        ),
        pk=pk,
    )


def _detail_redirect(request, hearing):
    """Pencere içinde HTMX işlemi bitince ayrıntı sayfası yeniden yüklenir."""
    suffix = "?pencere=1" if request.GET.get("pencere") else ""
    return HttpResponse(
        status=204,
        headers={"HX-Redirect": reverse("hearings:detail", args=[hearing.pk]) + suffix},
    )


class HearingListView(View):
    """Duruşma listesi takvimin "Liste" görünümüdür."""

    def get(self, request):
        query = request.GET.copy()
        query["view"] = "list"
        return redirect(reverse("agenda:calendar") + "?" + query.urlencode())


def _excuse_task_message(request, hearing):
    """Katılma durumu mazeretse sorumluya mazeret dilekçesi görevi açılır."""
    from apps.tasks.services import ensure_excuse_task

    if not (hearing.excuse_submitted and hearing.uses_result_flow):
        return
    task = ensure_excuse_task(hearing, request.user)
    if task:
        messages.success(
            request,
            f"Mazeret dilekçesi görevi açıldı: {task.assignee}, son gün {task.due_date:%d.%m.%Y}.",
        )


@method_decorator(xframe_options_sameorigin, name="dispatch")
class HearingCreateStandaloneView(View):
    def get(self, request):
        form = HearingStandaloneForm(user=request.user)
        initial_case_id = request.GET.get("dosya")
        if initial_case_id:
            try:
                c = filter_visible_cases(Case.objects.all(), request.user).get(pk=initial_case_id)
                form.fields["case"].initial = c
            except (Case.DoesNotExist, ValueError):
                pass
        return render(request, "cases/hearing_form.html", {"form": form, "title": "Yeni Etkinlik"})

    def post(self, request):
        form = HearingStandaloneForm(request.POST, user=request.user)
        if form.is_valid():
            h = form.save(commit=False)
            h.created_by = request.user
            h.save()
            queue_hearing_google_sync(h)
            messages.success(request, "Kayıt başarıyla eklendi.")
            _excuse_task_message(request, h)
            if request.GET.get("pencere"):
                return HttpResponse("<script>window.parent.location.reload()</script>")
            next_url = _safe_next(request) or reverse("agenda:calendar")
            return redirect(next_url)
        return render(request, "cases/hearing_form.html", {"form": form, "title": "Yeni Etkinlik"})


@method_decorator(xframe_options_sameorigin, name="dispatch")
class HearingDetailView(View):
    """Yarın ve sonrası: bilgi ve düzenleme. Bugün ve öncesi: sonuç, bilgilendirme, görev."""

    def get(self, request, pk):
        hearing = _visible_hearing(request, pk)
        done = hearing.is_done and hearing.uses_result_flow
        context = {
            "hearing": hearing,
            "done": done,
            "tasks": hearing.tasks.select_related("assignee"),
        }
        if done:
            context["result_form"] = HearingResultForm(instance=hearing)
            context["note_form"] = HearingClientNoteForm(instance=hearing)
            if hearing.result.strip() and hearing.effective_client:
                message = format_hearing_result_message(hearing)
                context["wa_templates"] = {"Duruşma Sonucu": message}
                context["wa_preview"] = message
        return render(request, "cases/hearing_detail.html", context)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class HearingEditView(View):
    """Henüz yapılmamış (yarın ve sonrası) duruşmanın düzenlenmesi."""

    def _hearing(self, request, pk):
        hearing = _visible_hearing(request, pk)
        if hearing.is_done and hearing.uses_result_flow:
            raise PermissionDenied  # yapılmış duruşmada sonuç girilir, bilgi düzenlenmez
        return hearing

    def _render(self, request, form, hearing):
        inline = bool(request.htmx)
        return render(
            request,
            "cases/_hearing_form.html" if inline else "cases/hearing_form.html",
            {
                "form": form,
                "hearing": hearing,
                "inline": inline,
                "title": f"Duruşmayı Düzenle — {hearing.title_display}",
            },
        )

    def get(self, request, pk):
        hearing = self._hearing(request, pk)
        form = HearingStandaloneForm(instance=hearing, user=request.user)
        return self._render(request, form, hearing)

    def post(self, request, pk):
        hearing = self._hearing(request, pk)
        form = HearingStandaloneForm(request.POST, instance=hearing, user=request.user)
        if form.is_valid():
            h = form.save()
            queue_hearing_google_sync(h)
            messages.success(request, "Duruşma güncellendi.")
            _excuse_task_message(request, h)
            if request.htmx:
                return _detail_redirect(request, h)
            if request.GET.get("pencere"):
                return HttpResponse("<script>window.parent.location.reload()</script>")
            next_url = _safe_next(request) or (reverse("agenda:calendar") + "?view=list")
            return redirect(next_url)
        return self._render(request, form, hearing)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class HearingResultView(View):
    """Yapılmış duruşmanın sonucu (verilen karar) ve isteğe bağlı sonraki duruşma tarihi."""

    def _hearing(self, request, pk):
        hearing = _visible_hearing(request, pk)
        if not (hearing.is_done and hearing.uses_result_flow):
            raise PermissionDenied
        return hearing

    def get(self, request, pk):
        hearing = self._hearing(request, pk)
        return render(
            request,
            "cases/_hearing_result_form.html",
            {"hearing": hearing, "result_form": HearingResultForm(instance=hearing)},
        )

    def post(self, request, pk):
        hearing = self._hearing(request, pk)
        form = HearingResultForm(request.POST, instance=hearing)
        if not form.is_valid():
            return render(
                request,
                "cases/_hearing_result_form.html",
                {"hearing": hearing, "result_form": form},
            )
        with transaction.atomic():
            h = form.save(commit=False)
            h.decisions = h.result
            h.status = HearingStatus.POSTPONED if h.excuse_submitted else HearingStatus.HELD
            h.save()
            if h.case_id:
                CaseEvent.objects.update_or_create(
                    case=h.case,
                    kind=CaseEvent.Kind.HEARING,
                    date=timezone.localtime(h.starts_at).date(),
                    title=f"{h.get_kind_display()} yapıldı",
                    defaults={"description": h.result, "created_by": request.user},
                )
            next_at = form.cleaned_data.get("next_hearing_at")
            next_hearing = None
            if next_at and h.case_id:
                next_hearing = Hearing.objects.filter(case_id=h.case_id, starts_at=next_at).first()
                if next_hearing is None:
                    next_hearing = Hearing.objects.create(
                        case_id=h.case_id,
                        client_id=h.client_id,
                        assigned_to_id=h.assigned_to_id,
                        kind=h.kind,
                        starts_at=next_at,
                        authority=h.authority,
                        created_by=request.user,
                    )
        queue_hearing_google_sync(h)
        if next_hearing:
            queue_hearing_google_sync(next_hearing)
        messages.success(request, "Duruşma sonucu kaydedildi.")
        return _detail_redirect(request, h)


class HearingClientNoteView(View):
    """Müvekkile giden mesaja eklenen notu kaydeder; mesaj önizlemesi yenilenir."""

    http_method_names = ["post"]

    def post(self, request, pk):
        hearing = _visible_hearing(request, pk)
        if not (hearing.is_done and hearing.uses_result_flow):
            raise PermissionDenied
        form = HearingClientNoteForm(request.POST, instance=hearing)
        if form.is_valid():
            hearing.client_note = form.cleaned_data["client_note"].strip()
            hearing.save(update_fields=["client_note", "updated_at"])
        suffix = "?pencere=1" if request.GET.get("pencere") else ""
        return redirect(reverse("hearings:detail", args=[hearing.pk]) + suffix)


class HearingInformView(View):
    """Müvekkil bilgilendirme kaydı: WhatsApp açılınca veya başka yolla bildirilince işaretlenir."""

    http_method_names = ["post"]

    def post(self, request, pk):
        hearing = _visible_hearing(request, pk)
        method = request.POST.get("method")
        if method not in HearingInformMethod.values:
            return HttpResponse("Geçersiz bilgilendirme yolu.", status=400)
        if not (hearing.is_done and hearing.uses_result_flow) or not hearing.effective_client:
            raise PermissionDenied
        if not hearing.result.strip():
            return HttpResponse("Önce duruşma sonucunu girin.", status=400)
        hearing.client_informed = True
        hearing.client_informed_at = timezone.now()
        hearing.client_informed_by = request.user
        hearing.inform_method = method
        hearing.save(
            update_fields=[
                "client_informed",
                "client_informed_at",
                "client_informed_by",
                "inform_method",
                "updated_at",
            ]
        )
        if method == HearingInformMethod.OTHER:
            return _detail_redirect(request, hearing)
        return HttpResponse(status=204)  # WhatsApp penceresi açık kalır; kapanınca sayfa yenilenir


class HearingDeleteStandaloneView(PermissionRequiredMixin, View):
    required_permission = "hearings.delete"

    def post(self, request, pk):
        hearing = get_object_or_404(Hearing, pk=pk)
        delete_hearing_from_google(hearing)
        hearing.delete()
        messages.success(request, "Duruşma kaydı silindi.")
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=200)
            response["HX-Refresh"] = "true"
            return response
        return redirect(reverse("agenda:calendar") + "?view=list")


class HearingExportView(View):
    """Filtrelenmiş duruşma listesinin tamamını Excel (varsayılan) veya PDF olarak indirir."""

    def get(self, request):
        from apps.core.list_export import build_result, export_response, wants_export
        from apps.reports.base import Column

        queryset = list_context(request)["queryset"]
        rows = []
        for h in queryset:
            local = timezone.localtime(h.starts_at)
            rows.append(
                [
                    local.date(),
                    local.strftime("%H:%M"),
                    h.get_kind_display(),
                    tr_title(h.authority or (h.case.authority if h.case else "")),
                    tr_title(h.case.display_name) if h.case else h.title_display,
                    tr_title(h.effective_client or ""),
                    tr_title(h.assigned_to or ""),
                    h.attendance_label,
                    h.result or "",
                ]
            )
        columns = [
            Column("Tarih", "date", 0.9),
            Column("Saat", width=0.6),
            Column("Tür", width=1.0),
            Column("Mahkeme", width=2.2),
            Column("Dosya", width=2.2),
            Column("Müvekkil", width=1.8),
            Column("Sorumlu avukat", width=1.4),
            Column("Katılma durumu", width=1.1),
            Column("Sonuç", width=2.6),
        ]
        result = build_result(
            "Duruşma Listesi", f"{len(rows)} kayıt (süzgeçler uygulanmış)", columns, rows
        )
        return export_response(result, wants_export(request) or "xlsx")
