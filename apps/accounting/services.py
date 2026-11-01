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
        if entry.client_id != case.client_id:
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
