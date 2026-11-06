from django.core.management.base import BaseCommand

from apps.agenda.google_sync import retry_pending_google_syncs
from apps.office.models import OfficeSettings


class Command(BaseCommand):
    help = "Google Takvim eşitlemesi başarısız olmuş duruşmaları yeniden dener."

    def handle(self, *args, **options):
        if not OfficeSettings.load().google_calendar_api_enabled:
            return
        result = retry_pending_google_syncs()
        if not result["success"]:
            self.stderr.write(result["error"])
            return
        if result["total"]:
            self.stdout.write(
                f"{result['total']} bekleyen eşitlemeden {result['synced']} başarılı, "
                f"{result['errors']} yine başarısız."
            )
