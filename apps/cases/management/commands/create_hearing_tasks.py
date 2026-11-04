from django.core.management.base import BaseCommand

from apps.cases.hearing_tasks import create_due_hearing_tasks


class Command(BaseCommand):
    help = "Duruşmadan 1 gün önce sabah duruşma ve müvekkil bilgilendirme görevlerini üretir."

    def handle(self, *args, **options):
        tasks = create_due_hearing_tasks()
        self.stdout.write(
            self.style.SUCCESS(f"{len(tasks)} duruşma bilgilendirme görevi oluşturuldu.")
        )
