from django.apps import AppConfig


class ClientsConfig(AppConfig):
    name = "apps.clients"
    verbose_name = "Müvekkiller"

    def ready(self):
        from auditlog.registry import auditlog

        from . import models

        for m in (
            models.Client,
            models.ClientContact,
            models.ClientIban,
            models.ClientRepresentative,
            models.PowerOfAttorney,
            models.Party,
            models.WhatsAppSettings,
            models.WhatsAppContact,
            models.ClientAppointment,
        ):
            auditlog.register(m)
        auditlog.register(models.WhatsAppMessage, exclude_fields=["body", "template_parameters"])
        auditlog.register(models.WhatsAppReceipt)
