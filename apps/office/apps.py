from django.apps import AppConfig


class OfficeConfig(AppConfig):
    name = "apps.office"
    verbose_name = "Ofis"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import TaskType

        auditlog.register(TaskType)
