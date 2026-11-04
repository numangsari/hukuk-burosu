from django.core.management.base import BaseCommand, CommandError

from apps.core.folders import FolderError
from apps.imports.models import PortalNotice
from apps.imports.notice_folders import copy_notice_documents


class Command(BaseCommand):
    help = "Dosyayla eşleştirilmiş tebligat belgelerini ofis klasörüne kopyalar."

    def handle(self, *args, **options):
        notices = (
            PortalNotice.objects.filter(resolution_case__isnull=False, documents__isnull=False)
            .select_related("resolution_case", "resolution_case__client")
            .distinct()
        )
        copied = 0
        failed = 0
        for notice in notices:
            try:
                copied += copy_notice_documents(notice)
            except FolderError:
                failed += 1
        self.stdout.write(f"Kontrol edilen belge: {copied}; sorunlu tebligat: {failed}.")
        if failed:
            raise CommandError("Bazı tebligatlar kopyalanamadı; ofis klasörünü kontrol edin.")
