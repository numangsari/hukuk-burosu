import re

from django import forms
from django.utils import timezone

from apps.clients.models import ClientAppointment, ClientContact, WhatsAppSettings
from apps.core.forms import BootstrapMixin, DateTimeInput

from . import transport


class ContactSettingsForm(BootstrapMixin, forms.Form):
    phone = forms.ModelChoiceField(
        label="WhatsApp için kullanılacak telefon", queryset=ClientContact.objects.none()
    )
    opted_in = forms.BooleanField(label="Müvekkil WhatsApp mesajlarını kabul etti", required=False)
    reminders_enabled = forms.BooleanField(
        label="Duruşma ve randevu hatırlatmalarını gönder", required=False
    )

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].queryset = client.contacts.filter(kind="phone")
        self.fields[
            "phone"
        ].help_text = "Yeni numara eklemek için müvekkilin İletişim bölümünü kullanın."


class ComposeForm(BootstrapMixin, forms.Form):
    body = forms.CharField(label="Mesaj", max_length=4096, widget=forms.Textarea(attrs={"rows": 3}))
    request_id = forms.UUIDField(widget=forms.HiddenInput)


class AppointmentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ClientAppointment
        fields = ["title", "starts_at", "location", "status"]
        widgets = {"starts_at": DateTimeInput()}

    def clean_starts_at(self):
        value = self.cleaned_data["starts_at"]
        if not self.instance.pk and value <= timezone.now():
            raise forms.ValidationError("Yeni randevu için ileri bir tarih seçin.")
        return value


class OfficeSettingsForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = WhatsAppSettings
        fields = [
            "enabled",
            "reminder_hours",
            "language",
            "hearing_template",
            "appointment_template",
            "start_template",
        ]

    def clean(self):
        data = super().clean()
        for name in ("hearing_template", "appointment_template", "start_template"):
            value = data.get(name, "").strip()
            data[name] = value
            if value and not re.fullmatch(r"[a-z][a-z0-9_]{0,119}", value):
                self.add_error(
                    name,
                    "Onaylı mesajın yalnızca küçük harf, rakam ve alt çizgi içeren adını girin.",
                )
        if data.get("language") and not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", data["language"]):
            self.add_error("language", "Örneğin Türkçe için tr kullanın.")
        if data.get("enabled"):
            if not transport.configured() or not self.instance.webhook_verified_at:
                self.add_error(
                    "enabled",
                    "Resmî WhatsApp bağlantısı ve gelen mesaj bağlantısı henüz tamamlanmadı.",
                )
            for name in ("hearing_template", "appointment_template"):
                if not data.get(name):
                    self.add_error(name, "Gönderimi açmadan önce onaylı hatırlatma mesajını seçin.")
        return data
