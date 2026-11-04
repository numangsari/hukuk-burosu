"""Fiziki klasör ve klasör içi numara kuralları."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import ArchiveFolder, Case


def available_archive_slots(folder_name, case=None):
    folder = ArchiveFolder.objects.filter(name__iexact=folder_name).first() if folder_name else None
    if not folder or folder.capacity is None:
        current = []
        if (
            case
            and case.pk
            and case.archive_folder_no.casefold() == folder_name.casefold()
            and case.archive_no
        ):
            current = [case.archive_no]
        return current, folder
    occupied = Case.objects.filter(archive_folder_no__iexact=folder.name).exclude(
        pk=case.pk if case else None
    )
    used = {
        int(number)
        for number in occupied.values_list("archive_no", flat=True)
        if number.isascii() and number.isdigit()
    }
    numbers = [str(number) for number in range(1, folder.capacity + 1) if number not in used]
    if (
        case
        and case.archive_folder_no.casefold() == folder.name.casefold()
        and case.archive_no
        and case.archive_no not in numbers
    ):
        numbers.insert(0, case.archive_no)
    return numbers, folder


def validate_archive_location(folder_name, number, case=None, *, lock=False, import_legacy=False):
    if not folder_name:
        if (
            number
            and not import_legacy
            and not (
                case
                and case.pk
                and Case.objects.filter(
                    pk=case.pk, archive_folder_no="", archive_no=number
                ).exists()
            )
        ):
            raise ValidationError({"archive_folder_no": "Önce bir klasör seçin."})
        return
    folders = ArchiveFolder.objects
    if lock:
        folders = folders.select_for_update()
    folder = folders.filter(name__iexact=folder_name).first()
    if not folder and import_legacy:
        try:
            with transaction.atomic():
                folder = ArchiveFolder.objects.create(
                    name=folder_name, kind=ArchiveFolder.Kind.LEGACY
                )
        except IntegrityError:
            folder = folders.filter(name__iexact=folder_name).first()
    if not folder:
        if case and case.pk and case.archive_folder_no.casefold() == folder_name.casefold():
            return
        raise ValidationError({"archive_folder_no": "Önce fiziki klasörü oluşturun."})
    existing_location = bool(
        case
        and case.pk
        and Case.objects.filter(
            pk=case.pk, archive_folder_no__iexact=folder_name, archive_no__iexact=number
        ).exists()
    )
    if folder.capacity is None:
        if import_legacy or existing_location:
            return
        raise ValidationError({"archive_folder_no": "Önce klasörün kapasitesini belirleyin."})
    if existing_location:
        return
    if (
        not number
        or not number.isascii()
        or not number.isdigit()
        or not 1 <= int(number) <= folder.capacity
    ):
        raise ValidationError(
            {"archive_no": f"Dosya numarası 1 ile {folder.capacity} arasında olmalıdır."}
        )
    used = Case.objects.filter(archive_folder_no__iexact=folder.name).exclude(
        pk=case.pk if case else None
    )
    for existing in used.values_list("archive_no", flat=True):
        if existing.isascii() and existing.isdigit() and int(existing) == int(number):
            raise ValidationError(
                {"archive_no": "Bu klasörde aynı dosya numarası zaten kullanılıyor."}
            )
