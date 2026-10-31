from django.core.management.base import BaseCommand, CommandError

from apps.backups.models import BackupRecord
from apps.backups.services import run_backup, scheduled_due


class Command(BaseCommand):
    help = "Veritabanı ve belgelerin şifreli yedeğini alır."

    def add_arguments(self, parser):
        parser.add_argument(
            "--scheduled",
            action="store_true",
            help="Görev Zamanlayıcı için: bugün yedek alınmamışsa ve saat geldiyse yedekler.",
        )
        parser.add_argument("--update", action="store_true", help="Güncelleme öncesi yedek")

    def handle(self, *args, scheduled, update, **options):
        if scheduled and not scheduled_due():
            self.stdout.write("Yedek zamanı gelmedi veya bugün zaten alındı.")
            return
        kind = (
            BackupRecord.Kind.UPDATE
            if update
            else (BackupRecord.Kind.SCHEDULED if scheduled else BackupRecord.Kind.MANUAL)
        )
        rec = run_backup(kind)
        if rec.status != BackupRecord.Status.OK:
            raise CommandError(f"Yedek alınamadı: {rec.message}")
        self.stdout.write(self.style.SUCCESS(f"Yedek alındı: {rec.file_name} ({rec.size} bayt)"))
