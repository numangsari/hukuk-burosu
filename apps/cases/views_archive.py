"""Fiziki Arşiv modülü view'ları (arşiv listesi, gezgin, etiketler ve dışa aktarım)."""

import re

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case as DbCase
from django.db.models import Count, IntegerField, Q, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import ListView

from apps.accounts.models import User
from apps.core.pagination import page_size
from apps.core.permissions import filter_visible_cases
from apps.office.models import OfficeSettings

from .archive_locations import available_archive_slots, validate_archive_location
from .forms import ArchiveFolderForm
from .models import TYPE_LABELS, ArchiveFolder, Case, CaseStatus, CaseType


def _parse_int(val):
    try:
        return int(re.sub(r"\D", "", str(val)))
    except (ValueError, TypeError):
        return 999999


class ArchiveListView(ListView):
    template_name = "cases/archive_list.html"
    context_object_name = "cases"

    def get_queryset(self):
        user = self.request.user
        qs = filter_visible_cases(
            Case.objects.select_related("client", "responsible_lawyer"),
            user,
        )

        scope = self.request.GET.get("scope", "all")
        if scope == "open":
            qs = qs.filter(Q(status=CaseStatus.OPEN) | Q(archive_folder_no__icontains="Açık"))
        elif scope == "closed":
            qs = qs.filter(Q(status=CaseStatus.CLOSED) | Q(archive_folder_no__icontains="Kapalı"))
        elif scope == "enforcement":
            qs = qs.filter(
                Q(case_type=CaseType.ENFORCEMENT) | Q(archive_folder_no__icontains="İcra")
            )
        elif scope == "missing":
            qs = qs.filter(Q(archive_folder_no="") | Q(archive_no=""))

        folder = self.request.GET.get("klasor", "").strip()
        if folder:
            qs = qs.filter(archive_folder_no__iexact=folder)

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(archive_folder_no__icontains=q)
                | Q(archive_no__icontains=q)
                | Q(official_no__icontains=q)
                | Q(subject__icontains=q)
                | Q(authority__icontains=q)
                | Q(client__name__icontains=q)
            )

        case_type = self.request.GET.get("tur")
        if case_type:
            qs = qs.filter(case_type=case_type)

        lawyer_id = self.request.GET.get("avukat")
        if lawyer_id:
            qs = qs.filter(responsible_lawyer_id=lawyer_id)

        status = self.request.GET.get("durum")
        if status:
            qs = qs.filter(status=status)

        return qs.order_by("archive_folder_no", "archive_no", "-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        visible = filter_visible_cases(Case.objects.all(), user)

        # İstatistikler
        ctx["total_count"] = visible.count()
        ctx["missing_count"] = visible.filter(Q(archive_folder_no="") | Q(archive_no="")).count()
        ctx["open_count"] = visible.filter(
            Q(status=CaseStatus.OPEN) | Q(archive_folder_no__icontains="Açık")
        ).count()
        ctx["closed_count"] = visible.filter(
            Q(status=CaseStatus.CLOSED) | Q(archive_folder_no__icontains="Kapalı")
        ).count()
        ctx["enforcement_count"] = visible.filter(
            Q(case_type=CaseType.ENFORCEMENT) | Q(archive_folder_no__icontains="İcra")
        ).count()

        # Klasörler listesi (Filtre açılır kutusu ve Gezgin görünümü için)
        folder_rows = (
            visible.exclude(archive_folder_no="")
            .values("archive_folder_no")
            .annotate(
                total_files=Count("id"),
                open_files=Count(
                    DbCase(
                        When(status=CaseStatus.OPEN, then=1),
                        output_field=IntegerField(),
                    )
                ),
                closed_files=Count(
                    DbCase(
                        When(status=CaseStatus.CLOSED, then=1),
                        output_field=IntegerField(),
                    )
                ),
            )
            .order_by("archive_folder_no")
        )

        folder_rows = list(folder_rows)
        by_name = {row["archive_folder_no"].casefold(): row for row in folder_rows}
        for folder in ArchiveFolder.objects.all():
            row = by_name.get(folder.name.casefold())
            if row:
                row["capacity"] = folder.capacity
            elif not Case.objects.filter(archive_folder_no__iexact=folder.name).exists():
                folder_rows.append(
                    {
                        "archive_folder_no": folder.name,
                        "total_files": 0,
                        "open_files": 0,
                        "closed_files": 0,
                        "capacity": folder.capacity,
                    }
                )
        folder_rows.sort(key=lambda row: row["archive_folder_no"].casefold())
        ctx["folder_list"] = folder_rows
        ctx["folder_count"] = len(folder_rows)

        ctx["current_scope"] = self.request.GET.get("scope", "all")
        ctx["view_mode"] = self.request.GET.get("view", "table")
        ctx["type_labels"] = TYPE_LABELS
        ctx["lawyers"] = User.objects.filter(
            is_active=True, role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER]
        ).order_by("first_name", "last_name")

        # Sayfalama (sadece tablo görünümünde)
        if ctx["view_mode"] != "explorer":
            paginator = Paginator(ctx["cases"], page_size(self.request))
            page_obj = paginator.get_page(self.request.GET.get("page"))
            ctx["page_obj"] = page_obj
            ctx["cases"] = page_obj.object_list

        return ctx

    def render_to_response(self, context, **response_kwargs):
        if self.request.headers.get("HX-Request") and not self.request.headers.get("HX-Boosted"):
            if context.get("view_mode") == "explorer":
                return render(self.request, "cases/_archive_explorer.html", context)
            return render(self.request, "cases/_archive_table.html", context)
        return super().render_to_response(context, **response_kwargs)


class ArchiveFolderDetailView(View):
    """Bir klasörün içindeki tüm dosyaları ve boşta kalan dosya numaralarını listeler."""

    def get(self, request, folder_name):
        user = request.user
        folder = ArchiveFolder.objects.filter(name__iexact=folder_name).first()
        visible = filter_visible_cases(Case.objects.all(), user)
        cases = list(
            visible.filter(archive_folder_no__iexact=folder_name)
            .select_related("client", "responsible_lawyer")
            .order_by("archive_no")
        )

        # Dosya numaralarını sayısal olarak sıralayalım
        def sort_key(c):
            return _parse_int(c.archive_no)

        cases_sorted = sorted(cases, key=sort_key)

        # Boşta / Atlanmış dosya numaralarını tespit etme
        raw_numbers = list(
            Case.objects.filter(archive_folder_no__iexact=folder_name).values_list(
                "archive_no", flat=True
            )
        )
        used_numbers = [
            int(number)
            for number in raw_numbers
            if number.isascii() and number.isdigit() and int(number) > 0
        ]
        needs_review = len(used_numbers) != len(raw_numbers) or len(set(used_numbers)) != len(
            used_numbers
        )

        missing_numbers = []
        if used_numbers:
            min_num = 1
            max_num = max(used_numbers)
            used_set = set(used_numbers)
            for i in range(min_num, max_num):
                if i not in used_set:
                    missing_numbers.append(i)
            next_suggested = max_num + 1
        else:
            next_suggested = 1
        if folder and folder.capacity:
            used_set = set(used_numbers)
            available = [n for n in range(1, folder.capacity + 1) if n not in used_set]
            missing_numbers = available
            next_suggested = available[0] if available else None

        return render(
            request,
            "cases/archive_folder_detail.html",
            {
                "folder_name": folder_name,
                "cases": cases_sorted,
                "total_cases": len(cases_sorted),
                "missing_numbers": missing_numbers[:20],
                "next_suggested": next_suggested,
                "folder": folder,
                "needs_review": needs_review,
            },
        )

    def post(self, request, folder_name):
        raw = request.POST.get("capacity", "")
        if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 32767:
            messages.error(request, "Kapasite 1 ile 32767 arasında olmalıdır.")
        else:
            with transaction.atomic():
                folder = get_object_or_404(
                    ArchiveFolder.objects.select_for_update(), name__iexact=folder_name
                )
                numbers = list(
                    Case.objects.filter(archive_folder_no__iexact=folder.name).values_list(
                        "archive_no", flat=True
                    )
                )
                invalid = any(
                    not n.isascii() or not n.isdigit() or not 1 <= int(n) <= int(raw)
                    for n in numbers
                )
                if invalid or len({int(n) for n in numbers if n.isascii() and n.isdigit()}) != len(
                    numbers
                ):
                    messages.error(
                        request,
                        "Mevcut dosya numaraları uygun değil; önce arşiv yerlerini düzenleyin.",
                    )
                else:
                    folder.capacity = int(raw)
                    folder.save(update_fields=["capacity", "updated_at"])
                    messages.success(request, "Klasör kapasitesi güncellendi.")
        return redirect("archive:folder_detail", folder_name=folder_name)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ArchiveFolderCreateView(View):
    def get(self, request):
        form = ArchiveFolderForm(
            initial={"capacity": OfficeSettings.load().archive_folder_default_capacity}
        )
        return render(request, "cases/archive_folder_form.html", {"form": form})

    def post(self, request):
        form = ArchiveFolderForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    ArchiveFolder.objects.create(
                        name=form.cleaned_data["full_name"],
                        kind=form.cleaned_data["kind"],
                        custom_kind=form.cleaned_data["custom_kind"]
                        if form.cleaned_data["kind"] == "other"
                        else "",
                        capacity=form.cleaned_data["capacity"],
                        created_by=request.user,
                    )
            except IntegrityError:
                form.add_error("name", "Bu klasör zaten var.")
            else:
                messages.success(request, "Fiziki klasör oluşturuldu.")
                if request.GET.get("pencere"):
                    return HttpResponse("<script>window.parent.location.reload()</script>")
                return redirect("archive:list")
        return render(request, "cases/archive_folder_form.html", {"form": form})


class ArchiveLocationUpdateView(View):
    """Dosyanın fiziki arşiv yerini (klasör no + dosya no) hızlı güncelleme penceresi."""

    def get(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        # Öneri klasör adları
        existing_folders = list(
            ArchiveFolder.objects.values_list("name", flat=True).order_by("name")
        )
        if case.archive_folder_no and case.archive_folder_no not in existing_folders:
            existing_folders.append(case.archive_folder_no)
        slots, folder = available_archive_slots(case.archive_folder_no, case)
        return render(
            request,
            "cases/_archive_location_modal.html",
            {
                "case": case,
                "existing_folders": existing_folders,
                "folder_value": case.archive_folder_no,
                "number_value": case.archive_no,
                "slots": slots,
                "capacity_missing": bool(folder and folder.capacity is None),
            },
        )

    def post(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        folder = request.POST.get("archive_folder_no", "").strip()
        number = request.POST.get("archive_no", "").strip()

        with transaction.atomic():
            try:
                validate_archive_location(folder, number, case, lock=True)
            except ValidationError as error:
                slots, selected_folder = available_archive_slots(folder, case)
                return render(
                    request,
                    "cases/_archive_location_modal.html",
                    {
                        "case": case,
                        "existing_folders": ArchiveFolder.objects.values_list("name", flat=True),
                        "errors": error.messages,
                        "folder_value": folder,
                        "number_value": number,
                        "slots": slots,
                        "capacity_missing": bool(
                            selected_folder and selected_folder.capacity is None
                        ),
                    },
                )
            case.archive_folder_no = folder
            if (
                number
                and number.isascii()
                and number.isdigit()
                and ArchiveFolder.objects.filter(
                    name__iexact=folder, capacity__isnull=False
                ).exists()
            ):
                number = str(int(number))
            case.archive_no = number
            case.save(update_fields=["archive_folder_no", "archive_no"])

        ref_text = case.archive_reference or "Boş"
        messages.success(request, f"{case.display_name} arşiv yeri güncellendi: {ref_text}")
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=200)
            response["HX-Refresh"] = "true"
            return response
        next_url = request.POST.get("next") or reverse("archive:list")
        return redirect(next_url)


def archive_available_slots(request):
    case = None
    raw_id = request.GET.get("case", "")
    if raw_id:
        if not raw_id.isascii() or not raw_id.isdigit():
            return JsonResponse({"error": "Geçersiz dosya."}, status=400)
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=raw_id)
    slots, folder = available_archive_slots(request.GET.get("folder", "").strip(), case)
    return JsonResponse(
        {"slots": slots, "capacity_missing": bool(folder and folder.capacity is None)}
    )


class ArchiveLabelsView(View):
    """Klasör sırtlığı veya dosya kapağı etiketi yazdırma şablonu."""

    def get(self, request):
        user = request.user
        visible = filter_visible_cases(Case.objects.all(), user)

        folder = request.GET.get("klasor", "").strip()
        case_ids = request.GET.getlist("dosya")
        # 'folder' (klasör sırtlığı) veya 'case' (dosya etiketi)
        label_type = request.GET.get("tip", "folder")

        cases = []
        folder_info = None

        if folder:
            cases = list(
                visible.filter(archive_folder_no__iexact=folder)
                .select_related("client")
                .order_by("archive_no")
            )
            cases.sort(key=lambda c: _parse_int(c.archive_no))
            folder_info = {
                "name": folder,
                "count": len(cases),
                "first_no": cases[0].archive_no if cases else "",
                "last_no": cases[-1].archive_no if cases else "",
            }
        elif case_ids:
            cases = list(visible.filter(pk__in=case_ids).select_related("client"))

        office = OfficeSettings.load()
        return render(
            request,
            "cases/archive_labels.html",
            {
                "label_type": label_type,
                "folder_info": folder_info,
                "cases": cases,
                "office": office,
            },
        )


class ArchiveExportView(View):
    """Arşiv listesini Excel (.xlsx) olarak indirir."""

    def get(self, request):
        import openpyxl
        from django.utils import timezone
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        view = ArchiveListView()
        view.request = request
        qs = view.get_queryset()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Fiziki Arşiv Envanteri"

        headers = [
            "Klasör No",
            "Dosya No",
            "Birleşik Arşiv Yeri",
            "Tür",
            "Kurum / Merci",
            "Dosya No / Konu",
            "Müvekkil",
            "Sorumlu Avukat",
            "Durum",
            "Açılış Tarihi",
            "Kapanış Tarihi",
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

        for c in qs:
            client = str(c.client or "")
            lawyer = str(c.responsible_lawyer or "")
            row_data = [
                c.archive_folder_no or "—",
                c.archive_no or "—",
                c.archive_reference or "—",
                c.get_case_type_display(),
                c.authority or "",
                f"{c.official_no or ''} {c.subject or ''}".strip(),
                client,
                lawyer,
                c.get_status_display(),
                c.opened_on.strftime("%d.%m.%Y") if c.opened_on else "",
                c.closed_on.strftime("%d.%m.%Y") if c.closed_on else "",
            ]
            ws.append(row_data)
            row_idx = ws.max_row
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                cell.font = Font(name="Calibri", size=10)
                if col_idx in (1, 2, 3, 4, 9, 10, 11):
                    cell.alignment = Alignment(horizontal="center", vertical="center")

        col_widths = {
            "A": 16,
            "B": 10,
            "C": 18,
            "D": 14,
            "E": 28,
            "F": 25,
            "G": 25,
            "H": 20,
            "I": 10,
            "J": 12,
            "K": 12,
        }
        for col_letter, width in col_widths.items():
            ws.column_dimensions[col_letter].width = width

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        today_str = timezone.localdate().strftime("%Y%m%d")
        filename = f"fiziki-arsiv-envanteri-{today_str}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        wb.save(response)
        return response
