from django import forms

from apps.core.forms import BootstrapMixin

from .models import OfficeSettings


class OfficeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = OfficeSettings
        fields = ["name", "address", "phone", "email", "tax_office", "tax_number", "logo"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class CalendarForm(BootstrapMixin, forms.ModelForm):
    """Gizli iCal adresi ekranda gösterilmez; boş bırakılırsa mevcut adres korunur."""

    clear = forms.BooleanField(label="Takvim bağlantısını kaldır", required=False)

    class Meta:
        model = OfficeSettings
        fields = ["calendar_ics_url"]
        widgets = {
            "calendar_ics_url": forms.PasswordInput(
                attrs={"placeholder": "https://calendar.google.com/calendar/ical/.../basic.ics"}
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["calendar_ics_url"].required = False
        self._previous = self.instance.calendar_ics_url

    def clean_calendar_ics_url(self):
        value = self.cleaned_data.get("calendar_ics_url", "").strip()
        if value and not value.startswith("https://"):
            raise forms.ValidationError("Adres https:// ile başlamalı.")
        return value

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("clear"):
            obj.calendar_ics_url = ""
        elif not self.cleaned_data.get("calendar_ics_url"):
            obj.calendar_ics_url = self._previous
        if commit:
            obj.save()
        return obj
