"""Fiziki klasör türleri ve sıralaması."""

import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from apps.office.models import OfficeSettings

from .models import ArchiveCategory, ArchiveFolder, CaseType

CASE_CATEGORY_NAMES = {
    CaseType.CIVIL: "Dava",
    CaseType.CRIMINAL: "Dava",
    CaseType.ADMINISTRATIVE: "Dava",
    CaseType.ENFORCEMENT: "İcra",
    CaseType.NOTICE: "İhtarname",
    CaseType.MEDIATION: "Arabuluculuk",
    CaseType.CONSULTANCY: "Sözleşme",
    CaseType.INVESTIGATION: "Soruşturma",
    CaseType.SALES_OFFICE: "Satış Memurluğu",
    CaseType.OTHER: "Diğer",
}


def natural_sort_key(val):
    """'Arabuluculuk 1', 'Arabuluculuk 2', 'Arabuluculuk 10' gibi dizeleri doğal sıralar."""
    if not val:
        return []
    from apps.core.text import tr_lower

    return [
        int(text) if text.isdigit() else tr_lower(text) for text in re.split(r"(\d+)", str(val))
    ]


def folder_name(category_name, state, number):
    clean_cat = category_name.strip()
    for prefix in ("Açık ", "Kapalı ", "açık ", "kapalı "):
        if clean_cat.startswith(prefix):
            clean_cat = clean_cat[len(prefix) :].strip()
            break
    if state == ArchiveFolder.PhysicalState.SINGLE:
        return f"{clean_cat} {number}"
    label = "Açık" if state == ArchiveFolder.PhysicalState.OPEN else "Kapalı"
    return f"{label} {clean_cat} {number}"


def next_folder_number(category, state):
    """Klasörün sıradaki numarasını veritabanındaki kayıtlı tamsayıdan üretir."""
    max_num = (
        ArchiveFolder.objects.filter(category=category, physical_state=state)
        .aggregate(largest=Max("number"))
        .get("largest")
    )
    if max_num is not None:
        return max_num + 1

    prefix = folder_name(category.name, state, "")
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.IGNORECASE)
    largest = 0
    for name in ArchiveFolder.objects.filter(name__istartswith=prefix).values_list(
        "name", flat=True
    ):
        match = pattern.fullmatch(name)
        if match:
            largest = max(largest, int(match.group(1)))
    return largest + 1


def category_for_case(case):
    """Dosyanın atanması gereken klasör kategorisini dinamik olarak tespit eder."""
    folder = getattr(case, "archive_folder", None)
    if not folder and case.archive_folder_no:
        folder = (
            ArchiveFolder.objects.select_related("category__client")
            .filter(name__iexact=case.archive_folder_no)
            .first()
        )
    if (
        folder
        and folder.category_id
        and (not folder.category.client_id or folder.category.client.physical_archive_enabled)
    ):
        return folder.category

    # Dinamik / Yapılandırılabilir veritabanı eşleştirmesi
    dynamic_category = ArchiveCategory.objects.filter(
        client__isnull=True,
        default_for_case_types__contains=case.case_type,
    ).first()
    if dynamic_category:
        return dynamic_category

    # Geriye dönük yedek eşleştirme (Fallback)
    name = CASE_CATEGORY_NAMES.get(case.case_type, "Diğer")
    return ArchiveCategory.objects.filter(name__iexact=name, client__isnull=True).first()


def validate_case_placement(case, state, folder_name_value, number, *, lock=False):
    from .archive_locations import validate_archive_location

    category = category_for_case(case)
    if not category or not category.tracks_state:
        return None
    if not folder_name_value and not number:
        return None
    if not folder_name_value or not number:
        raise ValidationError("Uygun klasörü ve boş dosya numarasını seçin.")
    folder = ArchiveFolder.objects.filter(name__iexact=folder_name_value).first()
    if not folder or folder.category_id != category.pk or folder.physical_state != state:
        raise ValidationError("Dosyanın türüne ve durumuna uygun bir klasör seçin.")
    validate_archive_location(folder_name_value, number, case, lock=lock)
    return folder


@transaction.atomic
def sync_client_archive(client, enabled, tracks_state, user):
    """Müvekkilin klasör tercihini eski yerleri silmeden uygular."""
    if not enabled:
        return
    OfficeSettings.load()
    office = OfficeSettings.objects.select_for_update().get(pk=1)
    category = ArchiveCategory.objects.select_for_update().filter(client=client).first()
    if category is None:
        base = client.name.replace("/", "-").replace("\\", "-").strip()
        name, suffix = base, 2
        while ArchiveCategory.objects.filter(name__iexact=name).exists():
            name = f"{base} ({suffix})"
            suffix += 1
        category = ArchiveCategory.objects.create(
            name=name, client=client, tracks_state=tracks_state, created_by=user
        )
    elif category.tracks_state != tracks_state:
        category.tracks_state = tracks_state
        category.save(update_fields=["tracks_state", "updated_at"])
    states = ("open", "closed") if tracks_state else ("single",)
    for folder in ArchiveFolder.objects.select_for_update().filter(category=category):
        active = folder.physical_state in states
        if folder.is_active != active:
            folder.is_active = active
            folder.save(update_fields=["is_active", "updated_at"])
    for state in states:
        if not ArchiveFolder.objects.filter(category=category, physical_state=state).exists():
            number = next_folder_number(category, state)
            ArchiveFolder.objects.create(
                name=folder_name(category.name, state, number),
                kind=ArchiveFolder.Kind.CATEGORY,
                category=category,
                physical_state=state,
                number=number,
                capacity=office.archive_folder_default_capacity,
                created_by=user,
            )
