from django.core.management.base import BaseCommand

from apps.clients.messaging.reminders import queue_reminders
from apps.clients.messaging.services import dispatch_pending


class Command(BaseCommand):
    help = "İzinli WhatsApp hatırlatmalarını hazırlar ve bekleyen mesajları gönderir."

    def handle(self, *args, **options):
        queued = queue_reminders()
        sent = dispatch_pending()
        self.stdout.write(f"{queued} hatırlatma hazırlandı; {sent} mesaj WhatsApp'a iletildi.")
