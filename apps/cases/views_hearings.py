"""Duruşmalar modülü view'ları (merkezi duruşma listesi, sonuç girme, takvim ve dışa aktarım)."""

import datetime as dt

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from apps.accounts.models import User
from apps.agenda.google_sync import delete_hearing_from_google, sync_hearing_to_google
from apps.core.pagination import page_size
from apps.core.permissions import AdminRequiredMixin, filter_visible_cases

from .forms import HearingForm, HearingResultForm, HearingStandaloneForm
from .models import Case, CaseEvent, Hearing, HearingKind, HearingStatus


class HearingListView(ListView):
    template_name = "cases/hearings_list.html"
    context_object_name = "hearings"

    def get_queryset(self):
        user = self.request.user
        visible_cases = filter_visible_cases(Case.objects.all(), user)
        qs = (
            Hearing.objects.filter(Q(case__in=visible_cases) | Q(case__isnull=True))
            .select_related(
                "case", "case__client", "case__responsible_lawyer", "client", "assigned_to"
            )
            .order_by("starts_at")
        )

        now = timezone.now()
        today = timezone.localdate()
        scope = self.request.GET.get("scope", "upcoming")

        if scope == "upcoming":
            qs = qs.filter(starts_at__gte=now).order_by("starts_at")
        elif scope == "today":
            qs = qs.filter(starts_at__date=today).order_by("starts_at")
        elif scope == "pending_result":
            qs = qs.filter(starts_at__lt=now, status=HearingStatus.PLANNED).order_by("starts_at")
        elif scope == "past":
            qs = qs.filter(Q(starts_at__lt=now) & ~Q(status=HearingStatus.PLANNED)).order_by(
                "-starts_at"
            )
        elif scope == "all":
            qs = qs.order_by("-starts_at")

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(case__official_no__icontains=q)
                | Q(case__subject__icontains=q)
                | Q(case__authority__icontains=q)
                | Q(authority__icontains=q)
                | Q(case__client__name__icontains=q)
                | Q(client__name__icontains=q)
                | Q(notes__icontains=q)
                | Q(result__icontains=q)
                | Q(room__icontains=q)
            )

        lawyer_id = self.request.GET.get("avukat")
        if lawyer_id:
            qs = qs.filter(Q(case__responsible_lawyer_id=lawyer_id) | Q(assigned_to_id=lawyer_id))

        kind = self.request.GET.get("tur")
        if kind:
            qs = qs.filter(kind=kind)

        status = self.request.GET.get("durum")
        if status:
            qs = qs.filter(status=status)

        start_date = self.request.GET.get("baslangic")
        if start_date:
            try:
                parsed_start = dt.date.fromisoformat(start_date)
                qs = qs.filter(starts_at__date__gte=parsed_start)
            except ValueError:
                pass

        end_date = self.request.GET.get("bitis")
        if end_date:
            try:
                parsed_end = dt.date.fromisoformat(end_date)
                qs = qs.filter(starts_at__date__lte=parsed_end)
            except ValueError:
                pass

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.now()
        today = timezone.localdate()

        visible_cases = filter_visible_cases(Case.objects.all(), user)
        base_qs = Hearing.objects.filter(case__in=visible_cases)

        ctx["today_count"] = base_qs.filter(starts_at__date=today).count()
        ctx["upcoming_count"] = base_qs.filter(starts_at__gte=now).count()
        ctx["pending_result_count"] = base_qs.filter(
            starts_at__lt=now, status=HearingStatus.PLANNED
        ).count()
        ctx["total_count"] = base_qs.count()

        ctx["lawyers"] = User.objects.filter(
            is_active=True,
            role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER],
        ).order_by("first_name", "last_name")
        ctx["hearing_kinds"] = HearingKind.choices
        ctx["hearing_statuses"] = HearingStatus.choices
        ctx["current_scope"] = self.request.GET.get("scope", "upcoming")
        ctx["now"] = now
        ctx["today"] = today

        # Sayfalama
        paginator = Paginator(ctx["hearings"], page_size(self.request))
        page_obj = paginator.get_page(self.request.GET.get("page"))
        ctx["page_obj"] = page_obj
        ctx["hearings"] = page_obj.object_list
        return ctx

    def render_to_response(self, context, **response_kwargs):
        if self.request.headers.get("HX-Request") and not self.request.headers.get("HX-Boosted"):
            return render(self.request, "cases/_hearings_list_table.html", context)
        return super().render_to_response(context, **response_kwargs)


class HearingCreateStandaloneView(View):
    def get(self, request):
        form = HearingStandaloneForm(user=request.user)
        initial_case_id = request.GET.get("dosya")
        if initial_case_id:
            try:
                c = Case.objects.get(pk=initial_case_id)
                form.fields["case"].initial = c
                form.fields["authority"].initial = c.authority
            except Case.DoesNotExist:
                pass
        return render(request, "cases/hearing_form.html", {"form": form, "title": "Yeni Duruşma"})

    def post(self, request):
        form = HearingStandaloneForm(request.POST, user=request.user)
        if form.is_valid():
            h = form.save(commit=False)
            h.created_by = request.user
            h.save()
            sync_hearing_to_google(h)
            messages.success(request, "Duruşma / etkinlik kaydı başarıyla eklendi.")
            next_url = request.POST.get("next") or reverse("agenda:calendar")
            return redirect(next_url)
        return render(
            request, "cases/hearing_form.html", {"form": form, "title": "Yeni Duruşma / Etkinlik"}
        )


class HearingResultModalView(View):
    """Duruşma sonucu / ara karar girme ekranı ve işlemi."""

    def get(self, request, pk):
        hearing = get_object_or_404(Hearing.objects.select_related("case"), pk=pk)
        form = HearingResultForm(instance=hearing)
        return render(
            request,
            "cases/_hearing_result_modal.html",
            {"hearing": hearing, "form": form},
        )

    def post(self, request, pk):
        hearing = get_object_or_404(Hearing.objects.select_related("case"), pk=pk)
        form = HearingResultForm(request.POST, instance=hearing)
        if form.is_valid():
            h = form.save()
            sync_hearing_to_google(h)
            if h.status != HearingStatus.PLANNED and h.result and h.case:
                text = f"{h.get_kind_display()} {h.get_status_display().lower()}"
                CaseEvent.objects.create(
                    case=h.case,
                    date=timezone.localtime(h.starts_at).date(),
                    kind=CaseEvent.Kind.HEARING,
                    title=text,
                    description=h.result,
                    created_by=request.user,
                )
            messages.success(request, "Duruşma sonucu kaydedildi.")
            if request.headers.get("HX-Request"):
                response = HttpResponse(status=200)
                response["HX-Refresh"] = "true"
                return response
            return redirect(reverse("agenda:calendar") + "?view=list")
        return render(
            request,
            "cases/_hearing_result_modal.html",
            {"hearing": hearing, "form": form},
        )


class HearingEditView(View):
    def get(self, request, pk):
        hearing = get_object_or_404(Hearing.objects.select_related("case"), pk=pk)
        form = HearingForm(instance=hearing)
        return render(
            request,
            "cases/hearing_form.html",
            {
                "form": form,
                "hearing": hearing,
                "title": f"Duruşmayı Düzenle — {hearing.case.display_name}",
            },
        )

    def post(self, request, pk):
        hearing = get_object_or_404(Hearing.objects.select_related("case"), pk=pk)
        form = HearingForm(request.POST, instance=hearing)
        if form.is_valid():
            h = form.save()
            sync_hearing_to_google(h)
            messages.success(request, "Duruşma güncellendi.")
            next_url = request.POST.get("next") or (reverse("agenda:calendar") + "?view=list")
            return redirect(next_url)
        return render(
            request,
            "cases/hearing_form.html",
            {
                "form": form,
                "hearing": hearing,
                "title": f"Duruşmayı Düzenle — {hearing.title_display}",
            },
        )


class HearingDeleteStandaloneView(AdminRequiredMixin, View):
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
    """Filtrelenmiş duruşma listesini Excel (.xlsx) olarak indirir."""

    def get(self, request):
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        view = HearingListView()
        view.request = request
        qs = view.get_queryset()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Duruşma Listesi"

        headers = [
            "Tarih",
            "Saat",
            "Tür",
            "Mahkeme / Merci",
            "Salon",
            "Dosya No / Konu",
            "Müvekkil",
            "Sorumlu Avukat",
            "Durum",
            "Sonuç / Ara Karar",
            "Notlar",
        ]

        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        thin_border = Border(
            left=Side(style="thin", color="D1D5DB"),
            right=Side(style="thin", color="D1D5DB"),
            top=Side(style="thin", color="D1D5DB"),
            bottom=Side(style="thin", color="D1D5DB"),
        )

        ws.append(headers)
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for h in qs:
            local_dt = timezone.localtime(h.starts_at)
            lawyer = str(h.case.responsible_lawyer or "")
            client = str(h.case.client or "")
            row_data = [
                local_dt.strftime("%d.%m.%Y"),
                local_dt.strftime("%H:%M"),
                h.get_kind_display(),
                h.authority or h.case.authority,
                h.room or "",
                f"{h.case.official_no or ''} {h.case.subject or ''}".strip(),
                client,
                lawyer,
                h.get_status_display(),
                h.result or "",
                h.notes or "",
            ]
            ws.append(row_data)
            row_idx = ws.max_row
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                cell.font = Font(name="Calibri", size=10)
                if col_idx in (1, 2, 3, 5, 9):
                    cell.alignment = Alignment(horizontal="center", vertical="center")

        col_widths = {
            "A": 12,
            "B": 8,
            "C": 14,
            "D": 32,
            "E": 10,
            "F": 25,
            "G": 25,
            "H": 20,
            "I": 12,
            "J": 35,
            "K": 20,
        }
        for col_letter, width in col_widths.items():
            ws.column_dimensions[col_letter].width = width

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        today_str = timezone.localdate().strftime("%Y%m%d")
        response["Content-Disposition"] = f'attachment; filename="durusma-listesi-{today_str}.xlsx"'
        wb.save(response)
        return response
