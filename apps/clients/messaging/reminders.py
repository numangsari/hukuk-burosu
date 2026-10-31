"""İzinli müvekkillere duruşma ve randevu hatırlatmalarını sıraya alır."""

import datetime as dt

from django.utils import timezone

from apps.cases.models import Hearing
from apps.clients.models import (
    ClientAppointment,
    WhatsAppContact,
    WhatsAppMessage,
    WhatsAppSettings,
)

from . import transport
from .services import recipient_ready, reminder_key


def queue_reminders(now=None):
    office = WhatsAppSettings.load()
    if not office.enabled or not transport.configured():
        return 0
    now = now or timezone.now()
    until = now + dt.timedelta(hours=office.reminder_hours)
    contacts = {
        contact.client_id: contact
        for contact in WhatsAppContact.objects.filter(
            opted_in=True, reminders_enabled=True, client__is_active=True
        ).select_related("client", "contact")
        if recipient_ready(contact)
    }
    sent = 0
    events = [
        (
            "hearing",
            office.hearing_template,
            Hearing.objects.filter(
                status="planned",
                kind__in=["hearing", "preliminary"],
                starts_at__gt=now,
                starts_at__lte=until,
                case__client_id__in=contacts,
            ).select_related("case"),
        ),
        (
            "appointment",
            office.appointment_template,
            ClientAppointment.objects.filter(
                status="planned",
                starts_at__gt=now,
                starts_at__lte=until,
                client_id__in=contacts,
            ),
        ),
    ]
    for kind, template, queryset in events:
        if not template:
            continue
        for event in queryset:
            client_id = event.case.client_id if kind == "hearing" else event.client_id
            contact = contacts[client_id]
            starts = timezone.localtime(event.starts_at)
            location = (event.authority if kind == "hearing" else event.location).strip()
            location = location or "Yer bilgisi için ofisimizle görüşün."
            parameters = [
                contact.client.name,
                starts.strftime("%d.%m.%Y"),
                starts.strftime("%H:%M"),
                location,
            ]
            key = reminder_key(kind, event, client_id, contact.phone_number)
            label = "Duruşma" if kind == "hearing" else "Randevu"
            message, created = WhatsAppMessage.objects.get_or_create(
                dedup_key=key,
                defaults={
                    "client_id": client_id,
                    "phone_number": contact.phone_number,
                    "direction": "outgoing",
                    "status": "queued",
                    "occurred_at": now,
                    "body": f"{label} hatırlatması · {parameters[1]} {parameters[2]} · {location}",
                    "template_name": template,
                    "template_parameters": parameters,
                    kind: event,
                },
            )
            if not created and message.status == WhatsAppMessage.Status.CANCELLED:
                updated = WhatsAppMessage.objects.filter(pk=message.pk, status="cancelled").update(
                    status="queued",
                    error="",
                    occurred_at=now,
                    template_name=template,
                    template_parameters=parameters,
                )
                sent += updated
            else:
                sent += created
    return sent
