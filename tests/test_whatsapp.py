import datetime as dt
import hashlib
import hmac
import io
import json
import secrets
import urllib.error
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import Hearing
from apps.clients.messaging import services, transport, webhooks
from apps.clients.messaging.phone import normalize_phone
from apps.clients.messaging.reminders import queue_reminders
from apps.clients.models import (
    ClientAppointment,
    WhatsAppMessage,
    WhatsAppSettings,
)

pytestmark = pytest.mark.django_db
CONFIG_NAMES = [
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_API_VERSION",
]


@pytest.fixture(autouse=True)
def isolate_whatsapp(monkeypatch, settings):
    # Arşivlenen ekranlar gerçek uygulamada açık değildir; yalnızca burada denenir.
    settings.ROOT_URLCONF = "tests.urls_archived_messaging"
    # Gerçek hesapla bağlantı kurulmaz; bütün telefon ve içerikler uydurmadır.
    for name in CONFIG_NAMES:
        monkeypatch.delenv(name, raising=False)
        setattr(settings, name, "")


@pytest.fixture
def channel(settings):
    for name in CONFIG_NAMES[:3]:
        setattr(settings, name, secrets.token_hex(24))
    settings.WHATSAPP_PHONE_NUMBER_ID = "100000000001"
    settings.WHATSAPP_API_VERSION = "v25.0"
    office = WhatsAppSettings.load()
    office.enabled = True
    office.hearing_template = "ornek_durusma"
    office.appointment_template = "ornek_randevu"
    office.start_template = "ornek_baslangic"
    office.webhook_verified_at = timezone.now()
    office.save()
    return office


@pytest.fixture
def recipient(client_factory, lawyer):
    owner = client_factory(first_name="Örnek", last_name="Müvekkil")
    phone = owner.contacts.create(kind="phone", value="0500 000 00 01")
    return services.set_contact(owner, phone, True, True, lawyer)


@pytest.fixture
def deliveries(monkeypatch):
    calls = []

    def deliver(message, language):
        calls.append(message.pk)
        return "wamid." + uuid4().hex

    monkeypatch.setattr(transport, "deliver", deliver)
    return calls


def incoming(recipient, *, when=None, body="Örnek mesaj", **kwargs):
    return WhatsAppMessage.objects.create(
        client=recipient.client,
        phone_number=recipient.phone_number,
        direction="incoming",
        status="received",
        occurred_at=when or timezone.now(),
        body=body,
        **kwargs,
    )


def payload(number, *, external_id=None, body="Örnek cevap", phone_id="100000000001"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone_id},
                            "messages": [
                                {
                                    "id": external_id or "wamid." + uuid4().hex,
                                    "from": number,
                                    "timestamp": str(int(timezone.now().timestamp())),
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ]
            }
        ],
    }


def post_callback(data, *, signed=True):
    body = json.dumps(data).encode()
    signature = (
        "sha256="
        + hmac.new(
            transport.config("WHATSAPP_APP_SECRET").encode(), body, hashlib.sha256
        ).hexdigest()
    )
    return HttpClient(enforce_csrf_checks=True).post(
        reverse("clients:messaging:webhook"),
        body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature if signed else "sha256=" + "0" * 64,
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0500 000 00 01", "905000000001"),
        ("5000000001", "905000000001"),
        ("+90 (500) 000-00-01", "905000000001"),
        ("00905000000001", "905000000001"),
        ("905000000001", "905000000001"),
        ("+44 20 0000 0000", "442000000000"),
    ],
)
def test_phone_normalization(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        None,
        "123",
        "05000000001 / 05000000002",
        "05000000001 dahili 2",
        "+90 05000000001",
        "javascript:123",
        "0" * 16,
        "٥٠٠٠٠٠٠٠٠١",
    ],
)
def test_invalid_phone_is_rejected(raw):
    with pytest.raises(ValidationError):
        normalize_phone(raw)


def test_sending_starts_disabled(recipient, lawyer, deliveries):
    with pytest.raises(ValidationError):
        services.compose(recipient.client, lawyer, "Örnek", uuid4())
    assert not WhatsAppSettings.load().enabled
    assert queue_reminders() == services.dispatch_pending() == 0
    assert deliveries == []


def test_reply_requires_recent_real_incoming_message(channel, recipient, lawyer):
    with pytest.raises(ValidationError):
        services.compose(recipient.client, lawyer, "Örnek", uuid4())
    incoming(recipient, when=timezone.now() - dt.timedelta(hours=25))
    incoming(recipient, message_type="system")
    with pytest.raises(ValidationError):
        services.compose(recipient.client, lawyer, "Örnek", uuid4())
    incoming(recipient)
    assert services.compose(recipient.client, lawyer, "Örnek", uuid4()).status == "queued"


def test_start_uses_approved_template_outside_reply_window(channel, recipient, lawyer, deliveries):
    message = services.compose(recipient.client, lawyer, "", uuid4(), start=True)
    assert message.template_name == "ornek_baslangic" and message.template_parameters == []
    assert services.dispatch(message.pk)
    assert deliveries == [message.pk]


def test_double_form_submission_only_sends_once(channel, recipient, lawyer, deliveries):
    incoming(recipient)
    request_id = uuid4()
    first = services.compose(recipient.client, lawyer, "Örnek cevap", request_id)
    assert services.dispatch(first.pk)
    second = services.compose(recipient.client, lawyer, "Örnek cevap", request_id)
    assert second.pk == first.pk
    assert not services.dispatch(second.pk)
    assert deliveries == [first.pk]
    assert first.created_by == lawyer
    with pytest.raises(ValidationError):
        services.compose(recipient.client, lawyer, "Farklı mesaj", request_id)


def test_only_definitely_failed_messages_can_be_retried(channel, recipient, lawyer, deliveries):
    incoming(recipient)
    message = services.compose(recipient.client, lawyer, "Örnek cevap", uuid4())
    message.status = "uncertain"
    message.save()
    with pytest.raises(ValidationError):
        services.retry_failed(message, lawyer)
    message.status = "failed"
    message.save()
    services.retry_failed(message, lawyer)
    assert services.dispatch(message.pk)
    assert deliveries == [message.pk]


@pytest.mark.parametrize("change", ["consent", "phone", "expired"])
def test_changed_recipient_or_window_stops_queued_message(
    channel, recipient, lawyer, deliveries, change
):
    incoming(recipient)
    message = services.compose(recipient.client, lawyer, "Örnek", uuid4())
    if change == "consent":
        recipient.opted_in = False
        recipient.save()
    elif change == "phone":
        recipient.contact.value = "0500 000 00 02"
        recipient.contact.save()
    else:
        WhatsAppMessage.objects.filter(direction="incoming").update(
            occurred_at=timezone.now() - dt.timedelta(hours=25)
        )
    assert not services.dispatch(message.pk)
    message.refresh_from_db()
    assert message.status == "cancelled" and deliveries == []


def test_phone_cannot_be_linked_to_two_clients(recipient, client_factory, lawyer):
    other = client_factory(first_name="Başka")
    phone = other.contacts.create(kind="phone", value="+905000000001")
    with pytest.raises(ValidationError, match="başka bir müvekkile"):
        services.set_contact(other, phone, True, True, lawyer)


def test_signature_and_phone_account_are_checked(channel, recipient):
    data = payload(recipient.phone_number)
    assert post_callback(data, signed=False).status_code == 403
    assert not WhatsAppMessage.objects.exists()
    assert (
        post_callback(payload(recipient.phone_number, phone_id="200000000001")).status_code == 200
    )
    assert not WhatsAppMessage.objects.exists()
    assert post_callback(data).status_code == 200
    assert WhatsAppMessage.objects.get().client == recipient.client
    assert post_callback(data).status_code == 200
    assert WhatsAppMessage.objects.count() == 1


def test_unknown_number_waits_for_explicit_link(channel, recipient, client_factory, lawyer):
    number = "905000000002"
    assert post_callback(payload(number)).status_code == 200
    message = WhatsAppMessage.objects.get()
    assert message.client is None
    other = client_factory(first_name="Örnek", last_name="Müvekkil")
    phone = other.contacts.create(kind="phone", value="05000000002")
    services.set_contact(other, phone, True, False, lawyer)
    message.refresh_from_db()
    assert message.client == other


def test_opt_out_cancels_pending_messages(channel, recipient, lawyer, deliveries):
    incoming(recipient)
    message = services.compose(recipient.client, lawyer, "Örnek", uuid4())
    assert (
        post_callback(payload(recipient.phone_number, body="Hatırlatmaları durdur")).status_code
        == 200
    )
    recipient.refresh_from_db()
    assert not recipient.opted_in and not recipient.reminders_enabled
    assert not services.dispatch(message.pk)
    assert deliveries == []


def test_verification_handshake_does_not_require_login(channel):
    response = HttpClient().get(
        reverse("clients:messaging:webhook"),
        {
            "hub.mode": "subscribe",
            "hub.verify_token": transport.config("WHATSAPP_VERIFY_TOKEN"),
            "hub.challenge": "ornek-dogrulama",
        },
    )
    assert response.status_code == 200 and response.content == b"ornek-dogrulama"
    assert WhatsAppSettings.load().webhook_verified_at is not None
    assert (
        HttpClient()
        .get(reverse("clients:messaging:webhook"), {"hub.verify_token": "yanlis"})
        .status_code
        == 403
    )


def test_receipts_are_monotonic_even_before_send_response(channel, recipient, lawyer, monkeypatch):
    incoming(recipient)
    message = services.compose(recipient.client, lawyer, "Örnek", uuid4())
    external_id = "wamid." + uuid4().hex

    def deliver(*args):
        webhooks.record_status(
            {"id": external_id, "status": "read", "timestamp": int(timezone.now().timestamp())}
        )
        return external_id

    monkeypatch.setattr(transport, "deliver", deliver)
    assert services.dispatch(message.pk)
    webhooks.record_status(
        {"id": external_id, "status": "sent", "timestamp": int(timezone.now().timestamp())}
    )
    message.refresh_from_db()
    assert message.status == "read"


def test_uncertain_delivery_is_not_automatically_retried(channel, recipient, lawyer, monkeypatch):
    incoming(recipient)
    message = services.compose(recipient.client, lawyer, "Örnek", uuid4())
    calls = []

    def fail(*args):
        calls.append(True)
        raise transport.DeliveryError("Örnek bağlantı kesintisi", uncertain=True)

    monkeypatch.setattr(transport, "deliver", fail)
    assert not services.dispatch(message.pk)
    assert services.dispatch_pending() == 0
    message.refresh_from_db()
    assert message.status == "uncertain" and len(calls) == 1


def test_reminders_only_queue_once_and_stop_after_event_change(
    channel, recipient, case_factory, deliveries
):
    now = timezone.now()
    case = case_factory(client=recipient.client)
    hearing = Hearing.objects.create(
        case=case, starts_at=now + dt.timedelta(hours=20), authority="Örnek Adliye"
    )
    appointment = ClientAppointment.objects.create(
        client=recipient.client,
        title="Özel iç not",
        starts_at=now + dt.timedelta(hours=10),
        location="Örnek ofis",
    )
    assert queue_reminders(now) == 2
    assert queue_reminders(now) == 0
    hearing.authority = "Yeni yer"
    hearing.save()
    appointment.status = "cancelled"
    appointment.save()
    assert services.dispatch_pending() == 0 and deliveries == []
    assert queue_reminders(now) == 1
    assert services.dispatch_pending() == 1
    message = WhatsAppMessage.objects.get(status="sent")
    assert message.template_parameters[-1] == "Yeni yer"
    assert "Özel iç not" not in message.body


def test_expired_cancelled_unconsented_events_are_not_reminded(channel, recipient, case_factory):
    now = timezone.now()
    case = case_factory(client=recipient.client)
    for hours, status in [(-1, "planned"), (30, "planned"), (5, "cancelled")]:
        Hearing.objects.create(case=case, starts_at=now + dt.timedelta(hours=hours), status=status)
    assert queue_reminders(now) == 0
    recipient.opted_in = False
    recipient.save()
    Hearing.objects.create(case=case, starts_at=now + dt.timedelta(hours=5))
    assert queue_reminders(now) == 0


def test_transport_uses_fixed_https_address_and_expected_payload(
    channel, recipient, lawyer, monkeypatch
):
    incoming(recipient)
    message = services.compose(recipient.client, lawyer, "Örnek gönderim", uuid4())
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return io.BytesIO(b'{"messages":[{"id":"wamid.ornek"}]}')

    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *args: Opener())
    assert transport.deliver(message, "tr") == "wamid.ornek"
    request, timeout = calls[0]
    assert request.full_url == "https://graph.facebook.com/v25.0/100000000001/messages"
    assert timeout == 15
    assert json.loads(request.data)["text"]["body"] == "Örnek gönderim"
    assert request.get_header("Authorization").startswith("Bearer ")


@pytest.mark.parametrize("kind", ["timeout", "server", "rejected", "invalid"])
def test_transport_errors_are_sanitized(channel, recipient, lawyer, monkeypatch, kind):
    incoming(recipient)
    message = services.compose(recipient.client, lawyer, "Örnek", uuid4())

    class Opener:
        def open(self, request, timeout):
            if kind == "timeout":
                raise TimeoutError("gizli-veri-gorunmemeli")
            if kind in ("server", "rejected"):
                raise urllib.error.HTTPError(
                    request.full_url,
                    500 if kind == "server" else 400,
                    "gizli-veri-gorunmemeli",
                    {},
                    None,
                )
            return io.BytesIO(b"gizli-veri-gorunmemeli")

    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(transport.DeliveryError) as exc:
        transport.deliver(message, "tr")
    assert "gizli-veri-gorunmemeli" not in str(exc.value)
    assert exc.value.uncertain == (kind != "rejected")


def test_pages_permissions_and_script_escaping(channel, recipient, lawyer_client, intern, client):
    incoming(recipient, body="<script>ornek()</script>")
    response = lawyer_client.get(reverse("clients:messaging:client", args=[recipient.client_id]))
    assert response.status_code == 200
    assert b"&lt;script&gt;ornek()&lt;/script&gt;" in response.content
    assert b"<script>ornek()</script>" not in response.content
    assert lawyer_client.get(reverse("clients:messaging:inbox")).status_code == 200
    client.force_login(intern)
    assert client.get(reverse("clients:messaging:settings")).status_code == 403
    client.logout()
    assert client.get(reverse("clients:messaging:inbox")).status_code == 302


def test_view_double_submission_and_appointment_lifecycle(
    channel, recipient, lawyer_client, deliveries
):
    incoming(recipient)
    url = reverse("clients:messaging:send", args=[recipient.client_id])
    data = {"body": "Örnek cevap", "request_id": str(uuid4())}
    assert lawyer_client.post(url, data).status_code == 302
    assert lawyer_client.post(url, data).status_code == 302
    assert len(deliveries) == 1
    starts_at = timezone.localtime(timezone.now() + dt.timedelta(days=1))
    response = lawyer_client.post(
        reverse("clients:messaging:appointment_add", args=[recipient.client_id]),
        {
            "title": "Örnek görüşme",
            "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"),
            "location": "Ofis",
            "status": "planned",
        },
    )
    assert response.status_code == 302
    appointment = ClientAppointment.objects.get()
    assert appointment.client == recipient.client
    lawyer_client.post(
        reverse("clients:messaging:appointment_cancel", args=[recipient.client_id, appointment.pk])
    )
    appointment.refresh_from_db()
    assert appointment.status == "cancelled"


def test_channel_cannot_be_activated_without_connection(admin_client_logged):
    response = admin_client_logged.post(
        reverse("clients:messaging:settings"),
        {
            "enabled": "on",
            "reminder_hours": 24,
            "language": "tr",
            "hearing_template": "ornek_durusma",
            "appointment_template": "ornek_randevu",
        },
    )
    assert response.status_code == 200 and "enabled" in response.context["form"].errors
    assert not WhatsAppSettings.load().enabled


def test_background_command_keeps_unconfigured_channel_idle(deliveries):
    output = io.StringIO()
    call_command("send_whatsapp", stdout=output)
    assert deliveries == [] and "0 mesaj" in output.getvalue()
