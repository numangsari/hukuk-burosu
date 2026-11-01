from django.apps import AppConfig


class CasesConfig(AppConfig):
    name = "apps.cases"
    verbose_name = "Dosyalar"

    def ready(self):
        from auditlog.registry import auditlog

        from . import models

        for m in (
            models.Case,
            models.CaseParty,
            models.CaseCoClient,
            models.Document,
            models.Hearing,
            models.CaseEvent,
            models.Seizure,
            models.SeizureRenewal,
        ):
            auditlog.register(m)
