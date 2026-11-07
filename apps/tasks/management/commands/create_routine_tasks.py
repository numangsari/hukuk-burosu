from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.tasks.routines import create_due_tasks


class Command(BaseCommand):
    help = "Günü gelen rutin görev kurallarından ofis içi görevleri bir kez oluşturur."

    def handle(self, *args, **options):
        try:
            created, skipped = create_due_tasks()
        except DatabaseError as error:
            raise CommandError("Rutin görev kontrolü veritabanına ulaşamadı.") from error
        self.stdout.write(f"{created} rutin görev oluşturuldu; {skipped} kuralda sorumlu pasif.")
