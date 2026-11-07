from django.apps import AppConfig


class AccountingConfig(AppConfig):
    name = "apps.accounting"
    verbose_name = "Muhasebe"

    def ready(self):
        from auditlog.registry import auditlog

        from . import models

        auditlog.register(models.LedgerEntry)
        auditlog.register(models.OfficeEntry)
