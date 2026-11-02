from django.apps import AppConfig


class ImportsConfig(AppConfig):
    name = "apps.imports"
    verbose_name = "Veri aktarımı"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import PowerOfAttorneyReview, PowerOfAttorneyReviewMember

        auditlog.register(PowerOfAttorneyReview, exclude_fields=["source_note"])
        auditlog.register(PowerOfAttorneyReviewMember)
