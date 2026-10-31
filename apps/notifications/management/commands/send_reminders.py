from django.core.management.base import BaseCommand

from apps.notifications.services import send_daily_reminders


class Command(BaseCommand):
    help = "Görev, duruşma ve tebligat hatırlatmalarını oluşturur; aynı bildirimi tekrarlamaz."

    def handle(self, *args, **options):
        count = send_daily_reminders()
        self.stdout.write(f"{count} hatırlatma oluşturuldu.")
