import time

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections

from apps.cases.seizures import create_due_tasks


class Command(BaseCommand):
    help = "Yenileme günü gelen hacizlerin görevlerini bir kez oluşturur."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Her dakika yeniden kontrol et.")

    def handle(self, *args, **options):
        try:
            while True:
                close_old_connections()
                try:
                    created, skipped = create_due_tasks()
                except DatabaseError as error:
                    if not options["watch"]:
                        raise CommandError(
                            "Haciz yenileme kontrolü veritabanına ulaşamadı."
                        ) from error
                    self.stderr.write(
                        "Veritabanına ulaşılamadı; bir dakika sonra tekrar denenecek."
                    )
                else:
                    if created or skipped or not options["watch"]:
                        self.stdout.write(
                            f"{created} haciz yenileme görevi oluşturuldu; "
                            f"{skipped} kayıtta sorumlular pasif."
                        )
                if not options["watch"]:
                    return
                time.sleep(60)
        except KeyboardInterrupt:
            return
