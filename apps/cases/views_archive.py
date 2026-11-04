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
from apps.clients.models import Client
from apps.core.pagination import page_size
from apps.core.permissions import filter_visible_cases, filter_visible_clients
from apps.core.text import tr_lower
from apps.office.models import OfficeSettings

from .archive_categories import folder_name, natural_sort_key, next_folder_number
from .archive_locations import available_archive_slots, validate_archive_location
from .forms import ArchiveCategoryForm, ArchiveFolderForm
from .models import ArchiveCategory, ArchiveFolder, Case, CaseStatus, CaseType


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
        if scope == "missing":
            qs = qs.filter(Q(archive_folder_no="") | Q(archive_no=""))
        elif scope == "client_specific":
            category_folders = ArchiveFolder.objects.filter(
                category__client__isnull=False
            ).values_list("name", flat=True)
            qs = qs.filter(archive_folder_no__in=category_folders)
        elif scope == "open":
            qs = qs.filter(
                Q(archive_folder__physical_state__in=["open", "single"])
                | (Q(archive_folder__isnull=True) & Q(status=CaseStatus.OPEN))
            )
        elif scope == "closed":
            qs = qs.filter(
                Q(archive_folder__physical_state="closed")
                | (Q(archive_folder__isnull=True) & Q(status=CaseStatus.CLOSED))
            )
        elif scope not in ("all",):
            matched_category = None
            for cat in ArchiveCategory.objects.all():
                slug = tr_lower(cat.name).replace(" ", "-")
                if (
                    slug == scope
                    or tr_lower(cat.name) == scope
                    or (scope in ("icra", "enforcement") and cat.name == "İcra")
                    or (scope == "sozlesme" and "sözleşme" in tr_lower(cat.name))
                ):
                    matched_category = cat
                    break

            if matched_category:
                category_folders = ArchiveFolder.objects.filter(
                    category=matched_category
                ).values_list("name", flat=True)
                filter_q = Q(archive_folder_no__in=category_folders)
                if matched_category.default_for_case_types:
                    filter_q |= Q(case_type__in=matched_category.default_for_case_types)
                elif matched_category.name == "Dava":
                    filter_q |= Q(
                        case_type__in=[
                            CaseType.CIVIL,
                            CaseType.CRIMINAL,
                            CaseType.ADMINISTRATIVE,
                        ]
                    )
                elif matched_category.name == "İcra":
                    filter_q |= Q(case_type=CaseType.ENFORCEMENT)
                elif matched_category.name == "Arabuluculuk":
                    filter_q |= Q(case_type=CaseType.MEDIATION)
                elif matched_category.name == "İhtarname":
                    filter_q |= Q(case_type=CaseType.NOTICE)
                elif matched_category.name == "Sözleşme":
                    filter_q |= Q(case_type=CaseType.CONSULTANCY)
                qs = qs.filter(filter_q)

        folder = self.request.GET.get("klasor", "").strip()
        if folder:
            qs = qs.filter(archive_folder_no__iexact=folder)

        kategori = self.request.GET.get("kategori", "").strip()
        if kategori:
            if kategori.isdigit():
                category_folders = ArchiveFolder.objects.filter(
                    category_id=int(kategori)
                ).values_list("name", flat=True)
            else:
                category_folders = ArchiveFolder.objects.filter(
                    category__name__iexact=kategori
                ).values_list("name", flat=True)
            qs = qs.filter(archive_folder_no__in=category_folders)

        client_filter = self.request.GET.get("muvekkil", "").strip()
        if client_filter and scope == "client_specific":
            qs = qs.filter(client_id=client_filter)

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(archive_folder_no__icontains=q) | Q(client__name__icontains=q))

        case_type = self.request.GET.get("tur")
        if case_type:
            qs = qs.filter(case_type=case_type)

        lawyer_id = self.request.GET.get("avukat")
        if lawyer_id:
            qs = qs.filter(responsible_lawyer_id=lawyer_id)

        status = self.request.GET.get("durum")
        if status:
            if status == "open":
                qs = qs.filter(
                    Q(archive_folder__physical_state__in=["open", "single"])
                    | (Q(archive_folder__isnull=True) & Q(status=CaseStatus.OPEN))
                )
            elif status == "closed":
                qs = qs.filter(
                    Q(archive_folder__physical_state="closed")
                    | (Q(archive_folder__isnull=True) & Q(status=CaseStatus.CLOSED))
                )

        return qs.order_by("archive_folder_no", "archive_no", "-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        visible = filter_visible_cases(Case.objects.all(), user)

        # İstatistikler
        ctx["total_count"] = visible.count()
        ctx["missing_count"] = visible.filter(Q(archive_folder_no="") | Q(archive_no="")).count()
        ctx["open_count"] = visible.filter(status=CaseStatus.OPEN).count()
        ctx["closed_count"] = visible.filter(status=CaseStatus.CLOSED).count()

        ctx["dava_count"] = visible.filter(
            Q(archive_folder__category__name="Dava")
            | Q(case_type__in=[CaseType.CIVIL, CaseType.CRIMINAL, CaseType.ADMINISTRATIVE])
        ).count()

        ctx["enforcement_count"] = visible.filter(
            Q(archive_folder__category__name="İcra") | Q(case_type=CaseType.ENFORCEMENT)
        ).count()

        ctx["other_special_count"] = visible.filter(
            Q(archive_folder__category__name__in=["Arabuluculuk", "İhtarname", "Sözleşme"])
            | Q(case_type__in=[CaseType.MEDIATION, CaseType.NOTICE, CaseType.CONSULTANCY])
        ).count()

        # Dinamik Arşiv Sekmeleri:
        # [Tümü] + [Genel Tipler (müvekkil hariç)] + [Müvekkile Özel] + [Arşiv Yeri Eksikler]
        general_categories = (
            ArchiveCategory.objects.filter(client__isnull=True, folders__isnull=False)
            .distinct()
            .order_by("id")
        )

        archive_tabs = [
            {"id": "all", "label": "Tümü", "scope": "all", "badge": None, "tracks_state": True}
        ]
        for cat in general_categories:
            slug = tr_lower(cat.name).replace(" ", "-")
            archive_tabs.append(
                {
                    "id": slug,
                    "label": cat.name,
                    "scope": slug,
                    "category_id": cat.id,
                    "category_name": cat.name,
                    "badge": None,
                    "tracks_state": cat.tracks_state,
                }
            )
        archive_tabs.append(
            {
                "id": "client_specific",
                "label": "Müvekkile Özel",
                "scope": "client_specific",
                "badge": None,
                "tracks_state": True,
            }
        )
        archive_tabs.append(
            {
                "id": "missing",
                "label": "Arşiv Yeri Eksikler",
                "scope": "missing",
                "badge": ctx["missing_count"],
                "tracks_state": False,
            }
        )
        ctx["archive_tabs"] = archive_tabs

        current_scope = self.request.GET.get("scope", "all")
        active_tab = next(
            (t for t in archive_tabs if t["scope"] == current_scope or t["id"] == current_scope),
            None,
        )
        ctx["show_state_filter"] = active_tab.get("tracks_state", True) if active_tab else False
        ctx["current_durum"] = self.request.GET.get("durum", "")

        # Klasörü olan müvekkillerin listesi (Yalnızca Müvekkile Özel sekmesinde)
        ctx["show_client_filter"] = current_scope == "client_specific"
        if ctx["show_client_filter"]:
            client_ids_with_folders = (
                ArchiveCategory.objects.filter(client__isnull=False)
                .values_list("client_id", flat=True)
                .distinct()
            )
            ctx["clients_with_folders"] = Client.objects.filter(
                id__in=client_ids_with_folders
            ).order_by("name")
        else:
            ctx["clients_with_folders"] = Client.objects.none()

        # Klasörler listesi (Filtre açılır kutusu ve Gezgin görünümü için)
        folder_stats = (
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
        )
        stats_by_name = {row["archive_folder_no"].casefold(): row for row in folder_stats}

        visible_clients = filter_visible_clients(Client.objects.all(), user)
        folders_qs = (
            ArchiveFolder.objects.select_related("category", "category__client")
            .filter(Q(category__client__isnull=True) | Q(category__client__in=visible_clients))
            .order_by("name")
        )

        all_folder_rows = []
        for folder in folders_qs:
            stat = stats_by_name.get(folder.name.casefold(), {})
            total = stat.get("total_files", 0)
            open_count = stat.get("open_files", 0)
            closed_count = stat.get("closed_files", 0)
            capacity = folder.capacity
            occupancy = min(100, int((total / capacity) * 100)) if capacity else 0
            all_folder_rows.append(
                {
                    "archive_folder_no": folder.name,
                    "folder_id": folder.id,
                    "category_id": folder.category_id,
                    "category_name": folder.category.name if folder.category else "Diğer",
                    "client_id": folder.category.client_id if folder.category else None,
                    "is_client_specific": bool(folder.category and folder.category.client_id),
                    "physical_state": folder.physical_state,
                    "physical_state_label": (
                        "Açık"
                        if folder.physical_state == "open"
                        else (
                            "Kapalı"
                            if folder.physical_state == "closed"
                            else ("Ayrımsız" if folder.physical_state == "single" else "")
                        )
                    ),
                    "total_files": total,
                    "open_files": open_count,
                    "closed_files": closed_count,
                    "capacity": capacity,
                    "occupancy_pct": occupancy,
                }
            )

        # Gezgin görünümü için filtreleme
        filtered_folder_rows = all_folder_rows

        # 1. Scope (Sekme / Kategori) filtresi
        scope = self.request.GET.get("scope", "all")
        if scope == "client_specific":
            filtered_folder_rows = [r for r in filtered_folder_rows if r["is_client_specific"]]
        elif scope in ("open", "closed"):
            if scope == "open":
                filtered_folder_rows = [
                    r for r in filtered_folder_rows if r["physical_state"] in ("open", "single")
                ]
            else:
                filtered_folder_rows = [
                    r for r in filtered_folder_rows if r["physical_state"] == "closed"
                ]
        elif scope not in ("all", "missing"):
            filtered_folder_rows = [
                r
                for r in filtered_folder_rows
                if (
                    tr_lower(r["category_name"]).replace(" ", "-") == scope
                    or tr_lower(r["category_name"]) == scope
                    or (
                        scope in ("icra", "enforcement")
                        and (
                            "icra" in tr_lower(r["archive_folder_no"])
                            or r["category_name"] == "İcra"
                        )
                    )
                    or (scope == "sozlesme" and "sözleşme" in tr_lower(r["category_name"]))
                )
            ]

        # 2. Durum Filtresi (Açık / Kapalı)
        status_filter = self.request.GET.get("durum", "").strip()
        if status_filter == "open":
            filtered_folder_rows = [
                r for r in filtered_folder_rows if r["physical_state"] in ("open", "single")
            ]
        elif status_filter == "closed":
            filtered_folder_rows = [
                r for r in filtered_folder_rows if r["physical_state"] == "closed"
            ]

        # 2. Klasör Türü (Kategori) filtresi
        kategori = self.request.GET.get("kategori", "").strip()
        if kategori:
            if kategori.isdigit():
                filtered_folder_rows = [
                    r for r in filtered_folder_rows if r["category_id"] == int(kategori)
                ]
            else:
                filtered_folder_rows = [
                    r
                    for r in filtered_folder_rows
                    if tr_lower(r["category_name"]) == tr_lower(kategori)
                ]

        # 3. Müvekkil filtresi (Yalnızca "client_specific" sekmesinde geçerli)
        client_filter = self.request.GET.get("muvekkil", "").strip()
        if client_filter and scope == "client_specific":
            filtered_folder_rows = [
                r
                for r in filtered_folder_rows
                if str(r.get("client_id") or "") == str(client_filter)
            ]

        # 4. Klasör adı seçimi
        folder_filter = self.request.GET.get("klasor", "").strip()
        if folder_filter:
            filtered_folder_rows = [
                r
                for r in filtered_folder_rows
                if tr_lower(r["archive_folder_no"]) == tr_lower(folder_filter)
            ]

        # 5. Arama (q: Yalnızca Klasör Adı/No ve Müvekkil)
        q = self.request.GET.get("q", "").strip()
        if q:
            q_lower = tr_lower(q)
            matching_folders_by_client = set(
                visible.filter(client__name__icontains=q)
                .exclude(archive_folder_no="")
                .values_list("archive_folder_no", flat=True)
            )
            matching_lower = {f.casefold() for f in matching_folders_by_client}
            filtered_folder_rows = [
                r
                for r in filtered_folder_rows
                if q_lower in tr_lower(r["archive_folder_no"])
                or r["archive_folder_no"].casefold() in matching_lower
            ]

        # Doğal Sıralama: 1, 2, ..., 9, 10
        filtered_folder_rows.sort(key=lambda row: natural_sort_key(row["archive_folder_no"]))
        all_folder_rows.sort(key=lambda row: natural_sort_key(row["archive_folder_no"]))

        ctx["folder_list"] = filtered_folder_rows
        ctx["all_folders"] = all_folder_rows
        ctx["folder_count"] = len(all_folder_rows)
        ctx["filtered_folder_count"] = len(filtered_folder_rows)

        # Klasör Türleri / Kategorileri (filtre açılır kutusu için)
        categories = ArchiveCategory.objects.filter(
            Q(client__isnull=True) | Q(client__in=visible_clients)
        ).order_by("name")
        ctx["categories"] = categories

        ctx["current_scope"] = self.request.GET.get("scope", "all")
        ctx["view_mode"] = "explorer"
        ctx["type_labels"] = CaseType.choices
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
        filter_q = Q(archive_folder_no__iexact=folder_name)
        if folder:
            filter_q |= Q(archive_folder=folder)
        cases = list(
            visible.filter(filter_q)
            .select_related("client", "responsible_lawyer")
            .distinct()
            .order_by("archive_no")
        )

        # Dosya numaralarını sayısal olarak sıralayalım
        def sort_key(c):
            return _parse_int(c.archive_no)

        cases_sorted = sorted(cases, key=sort_key)

        # Boşta / Atlanmış dosya numaralarını tespit etme
        raw_numbers = list(
            Case.objects.filter(filter_q).distinct().values_list("archive_no", flat=True)
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
            initial={"capacity": OfficeSettings.load().archive_folder_default_capacity},
            user=request.user,
        )
        return render(request, "cases/archive_folder_form.html", {"form": form})

    def post(self, request):
        form = ArchiveFolderForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    category = ArchiveCategory.objects.select_for_update().get(
                        pk=form.cleaned_data["category"].pk
                    )
                    state = form.cleaned_data["physical_state"]
                    number = next_folder_number(category, state)
                    name = folder_name(category.name, state, number)
                    if len(name) > 340:
                        raise ValidationError("Klasör adı çok uzun; daha kısa bir tür adı seçin.")
                    ArchiveFolder.objects.create(
                        name=name,
                        kind=ArchiveFolder.Kind.CATEGORY,
                        category=category,
                        physical_state=state,
                        number=number,
                        capacity=form.cleaned_data["capacity"],
                        created_by=request.user,
                    )
            except (IntegrityError, ValidationError):
                form.add_error(
                    None, "Klasör oluşturulamadı; türü ve sıradaki numarayı kontrol edin."
                )
            else:
                messages.success(request, "Fiziki klasör oluşturuldu.")
                if request.GET.get("pencere"):
                    return HttpResponse("<script>window.parent.location.reload()</script>")
                return redirect("archive:list")
        return render(request, "cases/archive_folder_form.html", {"form": form})


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ArchiveCategoryCreateView(View):
    def get(self, request):
        form = ArchiveCategoryForm(
            initial={"capacity": OfficeSettings.load().archive_folder_default_capacity}
        )
        return render(request, "cases/archive_category_form.html", {"form": form})

    def post(self, request):
        form = ArchiveCategoryForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    OfficeSettings.load()
                    OfficeSettings.objects.select_for_update().get(pk=1)
                    client = form.cleaned_data.get("client")
                    category = ArchiveCategory.objects.create(
                        name=form.cleaned_data["name"],
                        client=client,
                        tracks_state=form.cleaned_data["tracks_state"],
                        created_by=request.user,
                    )
                    if client and not client.physical_archive_enabled:
                        client.physical_archive_enabled = True
                        client.save(update_fields=["physical_archive_enabled", "updated_at"])
                    states = ("open", "closed") if category.tracks_state else ("single",)
                    for state in states:
                        ArchiveFolder.objects.create(
                            name=folder_name(category.name, state, 1),
                            kind=ArchiveFolder.Kind.CATEGORY,
                            category=category,
                            physical_state=state,
                            number=1,
                            capacity=form.cleaned_data["capacity"],
                            created_by=request.user,
                        )
            except IntegrityError:
                form.add_error("name", "Bu tür veya ilk klasör adı zaten var; farklı bir ad seçin.")
            else:
                messages.success(request, "Klasör türü ve ilk klasörleri oluşturuldu.")
                if request.GET.get("pencere"):
                    return HttpResponse("<script>window.parent.location.reload()</script>")
                return redirect("archive:list")
        return render(request, "cases/archive_category_form.html", {"form": form})


def archive_next_number(request):
    raw = request.GET.get("category", "")
    if not raw.isascii() or not raw.isdigit():
        return JsonResponse({"error": "Tür seçin."}, status=400)
    category = get_object_or_404(ArchiveCategory, pk=raw)
    if (
        category.client_id
        and not filter_visible_clients(Client.objects.all(), request.user)
        .filter(pk=category.client_id, physical_archive_enabled=True)
        .exists()
    ):
        return JsonResponse({"error": "Tür bulunamadı."}, status=404)
    state = request.GET.get("state", "open") if category.tracks_state else "single"
    if state not in (("open", "closed") if category.tracks_state else ("single",)):
        state = "open" if category.tracks_state else "single"
    num = next_folder_number(category, state)
    generated_name = folder_name(category.name, state, num)
    return JsonResponse(
        {
            "number": num,
            "folder_name": generated_name,
            "state": state,
            "tracks_state": category.tracks_state,
        }
    )


class ArchiveLocationUpdateView(View):
    """Dosyanın fiziki arşiv yerini (klasör no + dosya no) hızlı güncelleme penceresi."""

    def get(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        # Öneri klasör adları
        existing_folders = list(
            ArchiveFolder.objects.filter(is_active=True)
            .filter(Q(category__client__isnull=True) | Q(category__client_id=case.client_id))
            .values_list("name", flat=True)
        )
        existing_folders.sort(key=natural_sort_key)
        if case.archive_folder_no and case.archive_folder_no not in existing_folders:
            existing_folders.insert(0, case.archive_folder_no)
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
                err_folders = list(
                    ArchiveFolder.objects.filter(is_active=True)
                    .filter(
                        Q(category__client__isnull=True) | Q(category__client_id=case.client_id)
                    )
                    .values_list("name", flat=True)
                )
                err_folders.sort(key=natural_sort_key)
                if folder and folder not in err_folders:
                    err_folders.insert(0, folder)
                return render(
                    request,
                    "cases/_archive_location_modal.html",
                    {
                        "case": case,
                        "existing_folders": err_folders,
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
            case.save(update_fields=["archive_folder_no", "archive_no", "archive_folder"])

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
    raw_client = request.GET.get("client")
    if raw_client:
        if not raw_client.isascii() or not raw_client.isdigit():
            return JsonResponse({"error": "Geçersiz müvekkil."}, status=400)
        get_object_or_404(filter_visible_clients(Client.objects.all(), request.user), pk=raw_client)
    slots, folder = available_archive_slots(
        request.GET.get("folder", "").strip(), case, client_id=raw_client
    )
    return JsonResponse(
        {"slots": slots, "capacity_missing": bool(folder and folder.capacity is None)}
    )


def archive_available_folders(request):
    raw_client = request.GET.get("client", "")
    if raw_client:
        if not raw_client.isascii() or not raw_client.isdigit():
            return JsonResponse({"error": "Geçersiz müvekkil."}, status=400)
        get_object_or_404(filter_visible_clients(Client.objects.all(), request.user), pk=raw_client)
    names = list(
        ArchiveFolder.objects.filter(is_active=True)
        .filter(
            Q(category__client__isnull=True)
            | Q(category__client_id=raw_client if raw_client else None)
        )
        .values_list("name", flat=True)
    )
    names.sort(key=natural_sort_key)
    return JsonResponse({"folders": names})


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
