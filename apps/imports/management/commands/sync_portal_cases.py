from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.imports.models import PortalCase
from apps.imports.portal_case_sync import sync_portal_case
from apps.imports.portal_finance import import_finance


class Command(BaseCommand):
    help = "UYAP (PortalCase) kayıtlarını büro dosyaları (Case), taraflar ve safahat ile eşitler."

    def add_arguments(self, parser):
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Henüz büro dosyası olmayan UYAP kayıtları için yeni Case oluşturur.",
        )

    def handle(self, *args, **options):
        admin_user = (
            User.objects.filter(role="admin", is_active=True).order_by("pk").first()
            or User.objects.filter(is_active=True).order_by("pk").first()
        )
        create_missing = bool(options.get("create_missing"))
        synced = 0
        created_before = PortalCase.objects.filter(case__isnull=False).count()
        for record in PortalCase.objects.select_related("case").order_by("pk"):
            if not record.case_id and not create_missing:
                continue
            case = sync_portal_case(
                record,
                default_user=admin_user,
                create_missing=create_missing,
            )
            if case:
                import_finance(record)
                synced += 1
        created_after = PortalCase.objects.filter(case__isnull=False).count()
        self.stdout.write(
            f"{synced} UYAP kaydı eşitlendi (bağlı dosya: {created_before} -> {created_after})."
        )
