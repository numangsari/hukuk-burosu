"""Aynı müvekkilin para işlemlerini sıraya alır (emanet eksiye düşebilir)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.clients.models import Client

from .models import LedgerEntry


@transaction.atomic
def create_entry(entry: LedgerEntry) -> LedgerEntry:
    if entry.case_id:
        case = Case.objects.select_for_update().get(pk=entry.case_id)
        if entry.client_id not in case.client_ids():
            raise ValidationError("Dosyanın müvekkili değişti. Bilgileri yenileyip tekrar deneyin.")
    # Müvekkile ödeme ve mahsup emanet bakiyesini aşabilir (kullanıcı kararı).
    Client.objects.select_for_update().get(pk=entry.client_id)
    entry.save()
    return entry


@transaction.atomic
def cancel_entry(entry: LedgerEntry, user, reason: str) -> LedgerEntry:
    Client.objects.select_for_update().get(pk=entry.client_id)
    entry.refresh_from_db()
    if entry.is_cancelled:
        raise ValidationError("Bu hareket daha önce iptal edilmiş.")
    reason = reason.strip()
    if not reason:
        raise ValidationError("İptal nedeni yazılmalı.")
    # Emanet girişinin iptali emaneti eksiye düşürse de serbesttir (kullanıcı kararı).
    entry.is_cancelled = True
    entry.cancelled_at = timezone.now()
    entry.cancelled_by = user
    entry.cancel_reason = reason[:300]
    entry.save(
        update_fields=[
            "is_cancelled",
            "cancelled_at",
            "cancelled_by",
            "cancel_reason",
            "updated_at",
        ]
    )
    return entry


@transaction.atomic
def set_portal_exclusion(entry: LedgerEntry, user, exclude: bool, reason: str = "") -> LedgerEntry:
    """UYAP kaynaklı hareketi bakiye dışında bırakır veya geri alır (kayıt silinmez)."""
    Client.objects.select_for_update().get(pk=entry.client_id)
    entry.refresh_from_db()
    if not entry.portal_ref:
        raise ValidationError("Yalnızca UYAP'tan gelen hareket hesap dışı bırakılabilir.")
    if entry.is_cancelled:
        raise ValidationError("İptal edilmiş hareket üzerinde işlem yapılamaz.")
    reason = reason.strip()
    if exclude:
        if not reason:
            raise ValidationError("Hesap dışı bırakma nedeni yazılmalı.")
        if entry.excluded_from_balance:
            raise ValidationError("Bu hareket zaten hesap dışı.")
        entry.excluded_from_balance = True
        entry.excluded_at = timezone.now()
        entry.excluded_by = user
        entry.exclude_reason = reason[:300]
    else:
        if not entry.excluded_from_balance:
            raise ValidationError("Bu hareket zaten hesaba dahil.")
        entry.excluded_from_balance = False
        entry.excluded_at = None
        entry.excluded_by = None
        entry.exclude_reason = ""
    entry.save(
        update_fields=[
            "excluded_from_balance",
            "excluded_at",
            "excluded_by",
            "exclude_reason",
            "updated_at",
        ]
    )
    return entry
