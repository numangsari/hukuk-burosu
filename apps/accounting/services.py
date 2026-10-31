"""Aynı müvekkilin para işlemlerini bakiye kontrolüyle birlikte sıraya alır."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cases.models import Case
from apps.clients.models import Client
from apps.core.templatetags.ui import tl

from .models import EntryKind, LedgerEntry


@transaction.atomic
def create_entry(entry: LedgerEntry) -> LedgerEntry:
    if entry.case_id:
        case = Case.objects.select_for_update().get(pk=entry.case_id)
        if entry.client_id != case.client_id:
            raise ValidationError("Dosyanın müvekkili değişti. Bilgileri yenileyip tekrar deneyin.")
    Client.objects.select_for_update().get(pk=entry.client_id)
    if entry.kind in (EntryKind.TRUST_OUT, EntryKind.OFFSET):
        trust = LedgerEntry.objects.filter(client_id=entry.client_id).balances()["trust"]
        if entry.amount > trust:
            raise ValidationError(
                f"Emanet bakiyesi {tl(trust)}; bu tutardan fazla ödeme veya mahsup yapılamaz."
            )
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
    if entry.trust_effect > 0:
        trust = LedgerEntry.objects.filter(client_id=entry.client_id).balances()["trust"]
        if trust - entry.trust_effect < 0:
            raise ValidationError(
                "Bu iptal emanet bakiyesini eksiye düşürür. "
                "Önce bağlı ödeme veya mahsupları düzeltin."
            )
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
