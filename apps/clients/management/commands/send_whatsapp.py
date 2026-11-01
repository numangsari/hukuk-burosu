from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "WhatsApp bağlantısı kaldırıldığı için mesaj göndermez."

    def handle(self, *args, **options):
        self.stdout.write("WhatsApp bağlantısı kullanım dışı; 0 mesaj gönderildi.")
