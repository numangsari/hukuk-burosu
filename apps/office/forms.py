from django import forms

from apps.core.forms import BootstrapMixin

from .models import OfficeSettings, TaskType


class OfficeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = OfficeSettings
        fields = [
            "name",
            "address",
            "phone",
            "email",
            "tax_office",
            "tax_number",
            "logo",
            "idle_minutes",
        ]
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


class DocumentsRootForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = OfficeSettings
        fields = ["documents_root"]

    def clean_documents_root(self):
        from apps.core.folders import check_writable

        value = (self.cleaned_data.get("documents_root") or "").strip()
        if value and (error := check_writable(value)):
            raise forms.ValidationError(error)
        return value


class TaskTypeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = TaskType
        fields = ["name", "points", "requires_document", "is_active", "order"]

    def clean_name(self):
        from apps.core.text import tr_capitalize_words

        return tr_capitalize_words(self.cleaned_data["name"])


TaskTypeFormSet = forms.modelformset_factory(TaskType, form=TaskTypeForm, extra=1)


class BackupSettingsForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = OfficeSettings
        fields = ["backup_time", "backup_dir"]
        widgets = {"backup_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}
        labels = {"backup_dir": "Yedek kopyası klasörü (Google Drive / OneDrive)"}
        help_texts = {
            "backup_time": "Bu saatte PC kapalıysa yedek, PC açılınca alınır.",
            "backup_dir": "Yedekler önce sunucuda saklanır, ayrıca bu klasöre kopyalanır. "
            "Bulut senkron klasörü seçerseniz yedek buluta da gider.",
        }

    def clean_backup_dir(self):
        from apps.core.folders import check_writable

        value = (self.cleaned_data.get("backup_dir") or "").strip()
        if value and (error := check_writable(value)):
            raise forms.ValidationError(error)
        return value


class PortalLawyerAccessForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        from apps.imports.models import PortalLawyerAccess

        model = PortalLawyerAccess
        fields = ["user", "identity_number", "uyap_enabled", "uets_enabled"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User

        self.fields["user"].queryset = User.objects.filter(
            is_active=True, role__in=[User.Role.ADMIN, User.Role.LAWYER]
        )

    def clean_identity_number(self):
        from apps.core.validators import validate_tckn

        value = self.cleaned_data["identity_number"].strip()
        validate_tckn(value)
        return value
