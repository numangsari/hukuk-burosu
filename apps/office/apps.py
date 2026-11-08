from django.apps import AppConfig


class OfficeConfig(AppConfig):
    name = "apps.office"
    verbose_name = "Ofis"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import OfficeSettings, TaskType

        auditlog.register(TaskType)
        # Yetki matrisi ve ayar değişiklikleri izlenir; gizli anahtar, takvim adresi ve banka
        # bilgisi aktivite kaydına yazılmaz.
        auditlog.register(
            OfficeSettings,
            exclude_fields=["google_service_account_json", "calendar_ics_url", "bank_details"],
        )
