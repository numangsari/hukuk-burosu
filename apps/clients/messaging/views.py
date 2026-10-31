from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Max, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.clients.models import (
    Client,
    ClientAppointment,
    WhatsAppContact,
    WhatsAppMessage,
    WhatsAppSettings,
)
from apps.core.permissions import AdminRequiredMixin
from apps.core.text import fold

from . import services, transport
from .forms import AppointmentForm, ComposeForm, ContactSettingsForm, OfficeSettingsForm
from .phone import normalize_phone


class InboxView(ListView):
    template_name = "messaging/inbox.html"
    context_object_name = "conversations"

    def get_paginate_by(self, queryset):
        return self.request.user.page_size

    def get_queryset(self):
        last_ids = (
            WhatsAppMessage.objects.values("phone_number").annotate(last=Max("pk")).values("last")
        )
        qs = WhatsAppMessage.objects.filter(pk__in=Subquery(last_ids)).select_related("client")
        if q := self.request.GET.get("q", "").strip():
            qs = qs.filter(Q(client__search_key__contains=fold(q)) | Q(phone_number__contains=q))
        return qs.order_by("-created_at", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            whatsapp_settings=WhatsAppSettings.load(), connection_ready=transport.configured()
        )
        return context


def client_context(
    client, *, phone_form=None, compose_form=None, appointment_form=None, message_page=None
):
    contact = (
        WhatsAppContact.objects.select_related("client", "contact").filter(client=client).first()
    )
    initial = (
        {
            "phone": contact.contact_id,
            "opted_in": contact.opted_in,
            "reminders_enabled": contact.reminders_enabled,
        }
        if contact
        else {}
    )
    office = WhatsAppSettings.load()
    enabled = office.enabled and transport.configured() and services.recipient_ready(contact)
    page = Paginator(
        client.whatsapp_messages.select_related("created_by").order_by("-occurred_at", "-pk"), 50
    ).get_page(message_page)
    history = list(page)
    return {
        "client": client,
        "contact": contact,
        "whatsapp_settings": office,
        "connection_ready": transport.configured(),
        "phone_form": phone_form or ContactSettingsForm(client=client, initial=initial),
        "compose_form": compose_form or ComposeForm(initial={"request_id": uuid4()}),
        "appointment_form": appointment_form or AppointmentForm(),
        "chat_messages": list(reversed(history)),
        "message_page": page,
        "appointments": client.appointments.all(),
        "can_reply": bool(enabled and services.reply_window_open(contact.phone_number)),
        "can_start": bool(enabled and office.start_template),
        "start_request_id": uuid4(),
    }


class ClientMessagesView(View):
    def get(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        template = (
            "messaging/_messages.html"
            if request.GET.get("messages_only")
            else "messaging/client.html"
        )
        appointment = None
        if item_pk := request.GET.get("appointment"):
            if not item_pk.isascii() or not item_pk.isdecimal():
                raise Http404
            appointment = get_object_or_404(ClientAppointment, pk=item_pk, client=client)
        return render(
            request,
            template,
            client_context(
                client,
                message_page=request.GET.get("page"),
                appointment_form=AppointmentForm(instance=appointment) if appointment else None,
            ),
        )


class ContactSettingsView(View):
    def post(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        form = ContactSettingsForm(request.POST, client=client)
        if form.is_valid():
            try:
                services.set_contact(client, user=request.user, **form.cleaned_data)
            except (ValidationError, IntegrityError) as exc:
                form.add_error(
                    None,
                    exc
                    if isinstance(exc, ValidationError)
                    else "Bu numara başka bir kayıtta kullanılıyor.",
                )
            else:
                messages.success(request, "WhatsApp numarası ve mesaj tercihi kaydedildi.")
                return redirect("clients:messaging:client", pk=pk)
        return render(request, "messaging/client.html", client_context(client, phone_form=form))


class SendView(View):
    def post(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        start = request.POST.get("kind") == "start"
        form = ComposeForm(request.POST)
        if start:
            form.fields["body"].required = False
        if form.is_valid():
            try:
                message = services.compose(
                    client,
                    request.user,
                    form.cleaned_data.get("body", ""),
                    form.cleaned_data["request_id"],
                    start=start,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                services.dispatch(message.pk)
                message.refresh_from_db()
                if message.status in ("failed", "uncertain", "cancelled"):
                    messages.warning(request, message.error)
                else:
                    messages.success(request, f"Mesaj: {message.get_status_display()}.")
                return redirect("clients:messaging:client", pk=pk)
        return render(request, "messaging/client.html", client_context(client, compose_form=form))


class RetryView(View):
    def post(self, request, pk, message_pk):
        message = get_object_or_404(
            WhatsAppMessage, pk=message_pk, client_id=pk, direction="outgoing"
        )
        try:
            message = services.retry_failed(message, request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            services.dispatch(message.pk)
            message.refresh_from_db()
            if message.error:
                messages.warning(request, message.error)
            else:
                messages.success(request, f"Mesaj: {message.get_status_display()}.")
        return redirect("clients:messaging:client", pk=pk)


class UnknownConversationView(View):
    def get(self, request, phone):
        try:
            number = normalize_phone(phone, international=True)
        except ValidationError as exc:
            raise Http404 from exc
        contact = WhatsAppContact.objects.filter(phone_number=number).first()
        if contact:
            return redirect("clients:messaging:client", pk=contact.client_id)
        page = Paginator(
            WhatsAppMessage.objects.filter(phone_number=number).order_by("-occurred_at", "-pk"), 50
        ).get_page(request.GET.get("page"))
        if not page.object_list:
            raise Http404
        return render(
            request,
            "messaging/unknown.html",
            {
                "phone_number": number,
                "chat_messages": list(reversed(list(page))),
                "message_page": page,
            },
        )


class OfficeSettingsView(AdminRequiredMixin, View):
    def get(self, request):
        return render(
            request,
            "messaging/settings.html",
            {
                "form": OfficeSettingsForm(instance=WhatsAppSettings.load()),
                "connection_ready": transport.configured(),
            },
        )

    def post(self, request):
        form = OfficeSettingsForm(request.POST, instance=WhatsAppSettings.load())
        if form.is_valid():
            form.save()
            messages.success(request, "WhatsApp gönderim ayarları kaydedildi.")
            return redirect("clients:messaging:settings")
        return render(
            request,
            "messaging/settings.html",
            {"form": form, "connection_ready": transport.configured()},
        )


class AppointmentSaveView(View):
    @transaction.atomic
    def post(self, request, pk, item_pk=None):
        client = get_object_or_404(Client, pk=pk)
        instance = (
            get_object_or_404(
                ClientAppointment.objects.select_for_update(), pk=item_pk, client=client
            )
            if item_pk
            else None
        )
        form = AppointmentForm(request.POST, instance=instance)
        if form.is_valid():
            appointment = form.save(commit=False)
            appointment.client = client
            if not appointment.pk:
                appointment.created_by = request.user
            appointment.save()
            messages.success(request, "Randevu kaydedildi.")
            return redirect("clients:messaging:client", pk=pk)
        return render(
            request, "messaging/client.html", client_context(client, appointment_form=form)
        )


class AppointmentCancelView(View):
    def post(self, request, pk, item_pk):
        appointment = get_object_or_404(ClientAppointment, pk=item_pk, client_id=pk)
        appointment.status = ClientAppointment.Status.CANCELLED
        appointment.save(update_fields=["status", "updated_at"])
        messages.success(request, "Randevu iptal edildi.")
        return redirect("clients:messaging:client", pk=pk)
