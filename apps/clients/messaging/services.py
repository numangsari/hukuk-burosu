"""Ortak mesaj kutusu, alıcı onayı ve tekrarsız gönderim."""

import datetime as dt
import hashlib
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.clients.models import (
    Client,
    ContactKind,
    WhatsAppContact,
    WhatsAppMessage,
    WhatsAppReceipt,
    WhatsAppSettings,
)

from . import transport
from .phone import normalize_phone

S = WhatsAppMessage.Status
RANK = {"sent": 1, "failed": 2, "delivered": 3, "read": 4}


def recipient_ready(contact):
    if not contact or not contact.opted_in or not contact.contact:
        return False
    try:
        return (
            contact.contact.client_id == contact.client_id
            and contact.contact.kind == ContactKind.PHONE
            and normalize_phone(contact.contact.value) == contact.phone_number
        )
    except ValidationError:
        return False


def reply_window_open(phone_number, now=None):
    now = now or timezone.now()
    last = (
        WhatsAppMessage.objects.filter(
            phone_number=phone_number, direction=WhatsAppMessage.Direction.INCOMING
        )
        .exclude(message_type__in=["system", "unknown", "unsupported"])
        .aggregate(last=Max("occurred_at"))["last"]
    )
    return last is not None and now - dt.timedelta(hours=24) < last <= now


@transaction.atomic
def set_contact(client, phone, opted_in, reminders_enabled, user):
    Client.objects.select_for_update().get(pk=client.pk)
    if phone.client_id != client.pk or phone.kind != ContactKind.PHONE:
        raise ValidationError("Bu telefon seçilen müvekkile ait değil.")
    number = normalize_phone(phone.value)
    if WhatsAppContact.objects.filter(phone_number=number).exclude(client=client).exists():
        raise ValidationError("Bu WhatsApp numarası başka bir müvekkile bağlı.")
    if reminders_enabled and not opted_in:
        raise ValidationError("Hatırlatma göndermek için müvekkilin mesaj iznini kaydedin.")
    record = WhatsAppContact.objects.filter(client=client).first()
    if record is None:
        record = WhatsAppContact(client=client, created_by=user)
    changed_consent = record.opted_in != opted_in or record.phone_number != number
    record.contact, record.phone_number = phone, number
    record.opted_in, record.reminders_enabled = opted_in, reminders_enabled
    if changed_consent:
        record.consent_recorded_at = timezone.now()
        record.consent_recorded_by = user
    record.save()
    # Ada bakılarak eşleştirme yapılmaz; numarayı personel açıkça seçtikten sonra bağlanır.
    WhatsAppMessage.objects.filter(phone_number=number, client__isnull=True).update(client=client)
    if not opted_in:
        WhatsAppMessage.objects.filter(client=client, status=S.QUEUED).update(
            status=S.CANCELLED, error="Mesaj izni kapatıldı."
        )
    return record


def require_sending(contact):
    if not WhatsAppSettings.load().enabled or not transport.configured():
        raise ValidationError("WhatsApp bağlantısı henüz gönderime açılmadı.")
    if not recipient_ready(contact):
        raise ValidationError("Bu müvekkilin WhatsApp numarasını ve mesaj iznini kaydedin.")


@transaction.atomic
def compose(client, user, body, request_id, *, start=False):
    contact = (
        WhatsAppContact.objects.select_related("client", "contact").filter(client=client).first()
    )
    require_sending(contact)
    try:
        request_id = str(UUID(str(request_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Sayfayı yenileyip mesajı tekrar hazırlayın.") from exc
    key = f"manual:{user.pk}:{client.pk}:{request_id}"
    existing = WhatsAppMessage.objects.filter(dedup_key=key).first()
    if existing:
        if bool(existing.template_name) != start or (
            not start and existing.body != (body or "").strip()
        ):
            raise ValidationError(
                "Bu form daha önce farklı bir mesaj için kullanıldı. Sayfayı yenileyin."
            )
        return existing
    office = WhatsAppSettings.load()
    if start:
        if not office.start_template:
            raise ValidationError("Onaylı sohbet başlatma mesajı henüz seçilmedi.")
        body = "Onaylı sohbet başlatma mesajı"
    else:
        body = (body or "").strip()
        if not body or len(body) > 4096:
            raise ValidationError("Mesaj 1–4096 karakter arasında olmalı.")
        if not reply_window_open(contact.phone_number):
            raise ValidationError(
                "Müvekkilin son mesajından 24 saat geçti. "
                "Önce onaylı sohbet başlatma mesajını kullanın."
            )
    # Aynı formun eşzamanlı iki gönderimi tek kayıt üretir.
    message, _ = WhatsAppMessage.objects.get_or_create(
        dedup_key=key,
        defaults={
            "client": client,
            "phone_number": contact.phone_number,
            "direction": WhatsAppMessage.Direction.OUTGOING,
            "status": S.QUEUED,
            "body": body,
            "occurred_at": timezone.now(),
            "created_by": user,
            "template_name": office.start_template if start else "",
        },
    )
    return message


def reminder_key(kind, event, client_id, phone_number):
    location = event.authority if kind == "hearing" else event.location
    version = event.starts_at.astimezone(dt.UTC).isoformat() + "|" + location.strip()
    fingerprint = hashlib.sha256(version.encode()).hexdigest()[:24]
    return f"{kind}:{event.pk}:{fingerprint}:{client_id}:{phone_number}"


def reminder_is_current(message, contact, office, now):
    if not contact.reminders_enabled:
        return False
    if message.hearing_id:
        event = message.hearing
        valid = event.status == "planned" and event.case.client_id == message.client_id
        prefix, template = "hearing", office.hearing_template
    elif message.appointment_id:
        event = message.appointment
        valid = event.status == "planned" and event.client_id == message.client_id
        prefix, template = "appointment", office.appointment_template
    else:
        return False
    expected = reminder_key(prefix, event, message.client_id, contact.phone_number)
    return (
        valid
        and event.starts_at > now
        and expected == message.dedup_key
        and message.template_name == template
    )


@transaction.atomic
def claim(message_id):
    message = WhatsAppMessage.objects.select_for_update().get(pk=message_id)
    if message.status != S.QUEUED:
        return None
    office = WhatsAppSettings.load()
    if not office.enabled or not transport.configured():
        return None
    contact = (
        WhatsAppContact.objects.select_related("client", "contact")
        .filter(client_id=message.client_id)
        .first()
    )
    now = timezone.now()
    reason = ""
    if not recipient_ready(contact) or contact.phone_number != message.phone_number:
        reason = "Alıcı numarası veya mesaj izni değişti."
    elif message.dedup_key.startswith(("hearing:", "appointment:")):
        if not reminder_is_current(message, contact, office, now):
            reason = "Hatırlatmaya ait tarih, durum veya alıcı değişti."
        else:
            event = message.hearing if message.hearing_id else message.appointment
            if event.starts_at > now + dt.timedelta(hours=office.reminder_hours):
                return None
    elif message.occurred_at < now - dt.timedelta(hours=1):
        reason = "Uzun süredir bekleyen mesajın yeniden hazırlanması gerekiyor."
    elif not message.template_name and not reply_window_open(message.phone_number, now):
        reason = "Yanıt için izin verilen 24 saatlik süre doldu."
    if reason:
        message.status, message.error = S.CANCELLED, reason
        message.save(update_fields=["status", "error", "updated_at"])
        return None
    message.status, message.attempted_at = S.SENDING, now
    message.save(update_fields=["status", "attempted_at", "updated_at"])
    return message


@transaction.atomic
def apply_receipt(external_id):
    receipt = WhatsAppReceipt.objects.filter(external_id=external_id).first()
    message = (
        WhatsAppMessage.objects.select_for_update()
        .filter(external_id=external_id, direction=WhatsAppMessage.Direction.OUTGOING)
        .first()
    )
    if not receipt or not message:
        return
    if RANK.get(receipt.status, 0) > RANK.get(message.status, 0):
        message.status = receipt.status
        message.error = (
            "WhatsApp teslim edemedi; numarayı ve hesabı kontrol edin."
            if receipt.status == S.FAILED
            else ""
        )
        message.save(update_fields=["status", "error", "updated_at"])


def dispatch(message_id):
    message = claim(message_id)
    if message is None:
        return False
    try:
        external_id = transport.deliver(message, WhatsAppSettings.load().language)
    except transport.DeliveryError as exc:
        WhatsAppMessage.objects.filter(pk=message.pk, status=S.SENDING).update(
            status=S.UNCERTAIN if exc.uncertain else S.FAILED,
            error=str(exc),
            updated_at=timezone.now(),
        )
        return False
    try:
        with transaction.atomic():
            WhatsAppMessage.objects.filter(pk=message.pk, status=S.SENDING).update(
                external_id=external_id, status=S.SENT, error="", updated_at=timezone.now()
            )
    except IntegrityError:
        WhatsAppMessage.objects.filter(pk=message.pk, status=S.SENDING).update(
            status=S.UNCERTAIN, error="Gönderim yanıtı başka bir kayda ait; kontrol edin."
        )
        return False
    apply_receipt(external_id)
    return True


def dispatch_pending(limit=10):
    if not WhatsAppSettings.load().enabled or not transport.configured():
        return 0
    # İşlem gönderim sırasında kapanmış olabilir; bu kayıtlar kendiliğinden yeniden gönderilmez.
    WhatsAppMessage.objects.filter(
        status=S.SENDING, attempted_at__lt=timezone.now() - dt.timedelta(minutes=5)
    ).update(status=S.UNCERTAIN, error="Gönderim yarıda kaldı; WhatsApp üzerinden kontrol edin.")
    ids = list(
        WhatsAppMessage.objects.filter(status=S.QUEUED)
        .order_by("pk")
        .values_list("pk", flat=True)[:limit]
    )
    return sum(dispatch(pk) for pk in ids)


@transaction.atomic
def retry_failed(message, user):
    message = WhatsAppMessage.objects.select_for_update().get(pk=message.pk)
    if message.status != S.FAILED:
        raise ValidationError("Yalnızca gönderilemediği kesin olan mesaj tekrar denenebilir.")
    contact = (
        WhatsAppContact.objects.select_related("client", "contact")
        .filter(client_id=message.client_id)
        .first()
    )
    require_sending(contact)
    office = WhatsAppSettings.load()
    was_template = bool(message.template_name)
    if message.hearing_id:
        message.template_name = office.hearing_template
    elif message.appointment_id:
        message.template_name = office.appointment_template
    elif was_template:
        message.template_name = office.start_template
    if was_template and not message.template_name:
        raise ValidationError("Bu mesaj için onaylı hazır metin seçilmedi.")
    message.status, message.error = S.QUEUED, ""
    message.save(update_fields=["status", "error", "template_name", "updated_at"])
    return message
