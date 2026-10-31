"""WhatsApp'tan gelen imzalı mesajları ve teslim bilgilerini işler."""

import datetime as dt
import hashlib
import hmac
import json
import re

from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.clients.models import WhatsAppContact, WhatsAppMessage, WhatsAppReceipt, WhatsAppSettings
from apps.core.text import fold

from .phone import normalize_phone
from .services import RANK, apply_receipt
from .transport import config

MAX_BODY = 1024 * 1024
OPT_OUT = {"stop", "hatirlatmalari durdur", "whatsapp mesajlarini durdur"}


def _items(value):
    return value if isinstance(value, list) else []


def _object(value):
    return value if isinstance(value, dict) else {}


def _timestamp(value):
    try:
        stamp = dt.datetime.fromtimestamp(int(value), tz=dt.UTC)
        return stamp if stamp <= timezone.now() + dt.timedelta(minutes=5) else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


@transaction.atomic
def record_status(item):
    item = _object(item)
    external_id, status = item.get("id"), item.get("status")
    stamp = _timestamp(item.get("timestamp"))
    if (
        not isinstance(external_id, str)
        or not 1 <= len(external_id) <= 200
        or status not in RANK
        or not stamp
    ):
        return
    errors = _items(item.get("errors"))
    code = str(_object(errors[0]).get("code", "")) if errors else ""
    code = code if re.fullmatch(r"[0-9]{1,15}", code) else ""
    receipt, _ = WhatsAppReceipt.objects.get_or_create(
        external_id=external_id,
        defaults={"status": status, "occurred_at": stamp, "error_code": code},
    )
    receipt = WhatsAppReceipt.objects.select_for_update().get(pk=receipt.pk)
    if RANK[status] > RANK.get(receipt.status, 0):
        receipt.status, receipt.occurred_at, receipt.error_code = status, stamp, code
        receipt.save(update_fields=["status", "occurred_at", "error_code"])
    apply_receipt(external_id)


@transaction.atomic
def record_message(item):
    item = _object(item)
    external_id, stamp = item.get("id"), _timestamp(item.get("timestamp"))
    if not isinstance(external_id, str) or not 1 <= len(external_id) <= 200 or not stamp:
        return False
    try:
        number = normalize_phone(item.get("from"), international=True)
    except ValidationError:
        return False
    kind = item.get("type")
    if not isinstance(kind, str) or len(kind) > 20:
        return False
    body = _object(item.get("text")).get("body") if kind == "text" else None
    if not isinstance(body, str):
        body = "Bir medya veya belge mesajı alındı. İçeriğini WhatsApp üzerinden açın."
    contact = WhatsAppContact.objects.filter(phone_number=number).first()
    message, created = WhatsAppMessage.objects.get_or_create(
        external_id=external_id,
        defaults={
            "phone_number": number,
            "direction": "incoming",
            "status": "received",
            "body": body[:4096],
            "message_type": kind,
            "occurred_at": stamp,
            "client_id": contact.client_id if contact else None,
        },
    )
    if created and contact and fold(body).strip() in OPT_OUT:
        contact = WhatsAppContact.objects.select_for_update().get(pk=contact.pk)
        if (
            contact.consent_recorded_at is None
            or stamp + dt.timedelta(seconds=1) >= contact.consent_recorded_at
        ):
            contact.opted_in = contact.reminders_enabled = False
            contact.consent_recorded_at, contact.consent_recorded_by = stamp, None
            contact.save(
                update_fields=[
                    "opted_in",
                    "reminders_enabled",
                    "consent_recorded_at",
                    "consent_recorded_by",
                    "updated_at",
                ]
            )
            WhatsAppMessage.objects.filter(phone_number=number, status="queued").update(
                status="cancelled", error="Müvekkil WhatsApp mesajlarını durdurdu."
            )
    return created


def receive(payload):
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return 0
    count = 0
    for entry in _items(payload.get("entry")):
        for change in _items(_object(entry).get("changes")):
            change = _object(change)
            if change.get("field") != "messages":
                continue
            value = _object(change.get("value"))
            if _object(value.get("metadata")).get("phone_number_id") != config(
                "WHATSAPP_PHONE_NUMBER_ID"
            ):
                continue
            for item in _items(value.get("messages")):
                count += record_message(item)
            for item in _items(value.get("statuses")):
                record_status(item)
    return count


@csrf_exempt
@login_not_required
@require_http_methods(["GET", "POST"])
def webhook(request):
    if request.method == "GET":
        expected = config("WHATSAPP_VERIFY_TOKEN")
        supplied = request.GET.get("hub.verify_token", "")
        if (
            expected
            and request.GET.get("hub.mode") == "subscribe"
            and hmac.compare_digest(expected.encode(), supplied.encode())
        ):
            WhatsAppSettings.objects.update_or_create(
                pk=1, defaults={"webhook_verified_at": timezone.now()}
            )
            return HttpResponse(
                request.GET.get("hub.challenge", "")[:2000], content_type="text/plain"
            )
        return HttpResponse(status=403)
    secret = config("WHATSAPP_APP_SECRET")
    if not secret or not config("WHATSAPP_PHONE_NUMBER_ID"):
        return HttpResponse(status=503)
    if len(request.body) > MAX_BODY:
        return HttpResponse(status=413)
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
        return HttpResponse(status=403)
    expected = "sha256=" + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return HttpResponse(status=403)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeError):
        return HttpResponse(status=400)
    return JsonResponse({"received": receive(payload)})
