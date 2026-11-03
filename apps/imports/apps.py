from django.apps import AppConfig


class ImportsConfig(AppConfig):
    name = "apps.imports"
    verbose_name = "Veri aktarımı"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import (
            OfficeSourceRecord,
            PortalCapture,
            PortalCase,
            PortalConnection,
            PortalLawyerAccess,
            PortalNotice,
            PortalNoticeDocument,
            PowerOfAttorneyReview,
            PowerOfAttorneyReviewMember,
        )

        auditlog.register(PowerOfAttorneyReview, exclude_fields=["source_note"])
        auditlog.register(PowerOfAttorneyReviewMember)
        auditlog.register(OfficeSourceRecord, exclude_fields=["values"])
        auditlog.register(PortalCapture, exclude_fields=["data"])
        auditlog.register(PortalCase, exclude_fields=["data"])
        auditlog.register(PortalNotice, exclude_fields=["data", "subject"])
        auditlog.register(PortalNoticeDocument, exclude_fields=["original_name"])
        auditlog.register(PortalConnection, exclude_fields=["key_hash"])
        auditlog.register(PortalLawyerAccess, exclude_fields=["identity_number"])
