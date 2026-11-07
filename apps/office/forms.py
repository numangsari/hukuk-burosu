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
            "notice_default_due_days",
            "archive_folder_default_capacity",
            "use_assistant_assignee",
            "use_task_points",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["archive_folder_default_capacity"].required = False

    def clean_archive_folder_default_capacity(self):
        value = self.cleaned_data["archive_folder_default_capacity"]
        if value is None:
            return self.instance.archive_folder_default_capacity or 8
        if value < 1:
            raise forms.ValidationError("Kapasite en az 1 olmalıdır.")
        return value


class CalendarForm(BootstrapMixin, forms.ModelForm):
    """Ofis Google Takvim ayarları (iCal salt okunur ve Google Calendar API yazma)."""

    clear = forms.BooleanField(label="iCal takvim bağlantısını kaldır", required=False)
    clear_api_key = forms.BooleanField(
        label="Kayıtlı Service Account JSON anahtarını kaldır", required=False
    )

    class Meta:
        model = OfficeSettings
        fields = [
            "calendar_ics_url",
            "google_calendar_api_enabled",
            "google_calendar_id",
            "google_color_hearing",
            "google_color_discovery",
            "google_color_meeting",
            "google_color_mediation",
            "google_color_other",
            "google_service_account_json",
        ]
        widgets = {
            "calendar_ics_url": forms.PasswordInput(
                attrs={"placeholder": "https://calendar.google.com/calendar/ical/.../basic.ics"}
            ),
            "google_calendar_id": forms.TextInput(
                attrs={"placeholder": "primary veya ofis@gmail.com / ...@group.calendar.google.com"}
            ),
            "google_service_account_json": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": '{"type": "service_account", "project_id": "...", ...}',
                    "style": "font-family: monospace; font-size: 0.85rem;",
                }
            ),
        }
        labels = {
            "calendar_ics_url": "iCal gizli adresi",
            "google_calendar_api_enabled": "Duruşmaları Google Takvim'e otomatik aktar",
            "google_calendar_id": "Google Takvim ID",
            "google_color_hearing": "Duruşma / Ön İnceleme Rengi",
            "google_color_discovery": "Keşif Rengi",
            "google_color_meeting": "Müvekkil Görüşmesi / Toplantı Rengi",
            "google_color_mediation": "Arabuluculuk Rengi",
            "google_color_other": "Bilirkişi / Diğer Rengi",
            "google_service_account_json": "Google Service Account JSON anahtarı",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["calendar_ics_url"].required = False
        self.fields["google_calendar_id"].required = False
        for f in (
            "google_color_hearing",
            "google_color_discovery",
            "google_color_meeting",
            "google_color_mediation",
            "google_color_other",
            "google_service_account_json",
        ):
            self.fields[f].required = False
        self._previous_ics = self.instance.calendar_ics_url
        self._previous_json = self.instance.google_service_account_json
        if self._previous_json:
            self.fields["google_service_account_json"].widget.attrs["placeholder"] = (
                "Anahtar tanımlı. Değiştirmek istemiyorsanız boş bırakın."
            )
            self.initial["google_service_account_json"] = ""

    def clean_google_calendar_event_color(self):
        val = (self.cleaned_data.get("google_calendar_event_color") or "").strip()
        return val or "9"

    def clean_calendar_ics_url(self):
        value = self.cleaned_data.get("calendar_ics_url", "").strip()
        if value and not value.startswith("https://"):
            raise forms.ValidationError("Adres https:// ile başlamalı.")
        return value

    def clean_google_service_account_json(self):
        value = self.cleaned_data.get("google_service_account_json", "").strip()
        if not value:
            return ""
        import json

        try:
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError
        except Exception:
            raise forms.ValidationError(
                "Girilen Service Account anahtarı geçerli bir JSON formatında değil."
            ) from None
        return value

    def clean(self):
        cleaned_data = super().clean()
        api_enabled = cleaned_data.get("google_calendar_api_enabled")
        cal_id = (cleaned_data.get("google_calendar_id") or "").strip()
        clear_key = cleaned_data.get("clear_api_key")
        json_val = (
            ""
            if clear_key
            else (cleaned_data.get("google_service_account_json") or self._previous_json)
        )

        if api_enabled:
            if not cal_id:
                self.add_error("google_calendar_id", "API aktarımı açıkken Takvim ID zorunludur.")
            if not json_val:
                self.add_error(
                    "google_service_account_json",
                    "API aktarımı açıkken Service Account JSON anahtarı zorunludur.",
                )
        return cleaned_data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("clear"):
            obj.calendar_ics_url = ""
        elif not self.cleaned_data.get("calendar_ics_url"):
            obj.calendar_ics_url = self._previous_ics

        if self.cleaned_data.get("clear_api_key"):
            obj.google_service_account_json = ""
            obj.google_calendar_api_enabled = False
        elif not self.cleaned_data.get("google_service_account_json"):
            obj.google_service_account_json = self._previous_json

        if commit:
            obj.save()
        return obj


class DocumentsRootForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = OfficeSettings
        fields = ["documents_root", "backup_time"]
        widgets = {"backup_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}
        labels = {"documents_root": "Ofis klasörü", "backup_time": "Günlük yedek saati"}
        help_texts = {"backup_time": "Bilgisayar bu saatte kapalıysa açılınca yedek alınır."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["backup_time"].required = False
        from django.conf import settings

        if settings.DEBUG:
            import os
            from pathlib import Path

            startup = (
                Path(os.environ.get("APPDATA", ""))
                / "Microsoft/Windows/Start Menu/Programs/Startup"
            )
            enabled = any(
                (startup / name).is_file()
                for name in [
                    "Hukuk Burosu Gelistirme Yedek.lnk",
                    "Ozkurt Hukuk Gelistirme Yedek.lnk",
                ]
            )
            self.fields["backup_time"].help_text = (
                (
                    "Oturum açıkken otomatik kontrol çalışır; "
                    "bilgisayar kapalıysa açılınca yedek alınır."
                )
                if enabled
                else (
                    "Bu deneme ortamında otomatik kontrol kurulu değil; "
                    "Şimdi yedek al düğmesini kullanın."
                )
            )

    def clean_backup_time(self):
        return self.cleaned_data.get("backup_time") or self.instance.backup_time

    def clean_documents_root(self):
        from apps.core.folders import check_writable

        value = (self.cleaned_data.get("documents_root") or "").strip()
        if value and (error := check_writable(value)):
            raise forms.ValidationError(error)
        return value


class TaskTypeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = TaskType
        fields = [
            "name",
            "points",
            "requires_document",
            "requires_accounting",
            "is_active",
            "order",
        ]

    def clean_name(self):
        from apps.core.text import tr_capitalize_words

        return tr_capitalize_words(self.cleaned_data["name"])


TaskTypeFormSet = forms.modelformset_factory(TaskType, form=TaskTypeForm, extra=1, can_delete=True)


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
            is_active=True, role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER]
        )

    def clean_identity_number(self):
        from apps.core.validators import validate_tckn

        value = self.cleaned_data["identity_number"].strip()
        validate_tckn(value)
        return value


class AllowedHostsForm(BootstrapMixin, forms.ModelForm):
    """Sunucuya girilebilecek ek bilgisayar adı ve IP adreslerini düzenler."""

    MAX_HOSTS = 50

    class Meta:
        model = OfficeSettings
        fields = ["allowed_hosts"]
        widgets = {"allowed_hosts": forms.Textarea(attrs={"rows": 6, "spellcheck": "false"})}
        labels = {"allowed_hosts": "Ek erişim adresleri"}

    @staticmethod
    def _normalize(entry: str) -> str:
        import ipaddress
        import re

        if any(ch in entry for ch in r":/\@*?#") or entry.startswith(".") or entry.endswith("."):
            raise forms.ValidationError(
                f"'{entry}' geçersiz. Yalnızca bilgisayar adı veya IP yazın "
                "(http://, port numarası ve * kullanılmaz)."
            )
        if re.fullmatch(r"[0-9.]+", entry):
            try:
                return str(ipaddress.IPv4Address(entry))
            except ValueError:
                raise forms.ValidationError(f"'{entry}' geçerli bir IP adresi değil.") from None
        try:
            ascii_name = entry.encode("idna").decode("ascii")  # Türkçe karakterli ad -> punycode
        except UnicodeError:
            raise forms.ValidationError(f"'{entry}' geçerli bir bilgisayar adı değil.") from None
        label = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
        if not re.fullmatch(rf"{label}(\.{label})*", ascii_name):
            raise forms.ValidationError(f"'{entry}' geçerli bir bilgisayar adı değil.")
        return ascii_name

    def clean_allowed_hosts(self):
        from config.hosts import parse_hosts

        entries = parse_hosts(self.cleaned_data.get("allowed_hosts", ""))
        normalized = list(dict.fromkeys(self._normalize(e) for e in entries))
        if len(normalized) > self.MAX_HOSTS:
            raise forms.ValidationError(f"En fazla {self.MAX_HOSTS} adres girilebilir.")
        return "\n".join(normalized)
