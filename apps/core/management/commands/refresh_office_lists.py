"""Ofis klasöründeki görüntüleme tablolarını günceller."""

import time

from django.core.management.base import BaseCommand, CommandError

from apps.core.office_lists import OfficeListsError, update_office_lists


class Command(BaseCommand):
    help = "Ofis klasöründeki görüntüleme tablolarını yeniler."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Listeleri düzenli olarak denetle")

    def handle(self, *args, watch=False, **options):
        while True:
            started = time.monotonic()
            try:
                result = update_office_lists()
                if result.get("busy"):
                    message = "Başka bir güncelleme sürüyor."
                elif result.get("issues"):
                    message = "Bazı listeler güncellenemedi; ofis klasörü ayarlarına bakın."
                else:
                    message = "Listeler güncel."
            except OfficeListsError as exc:
                message = str(exc)
                if not watch:
                    raise CommandError(message) from exc
            except Exception as exc:
                message = "Liste güncellemesi tamamlanamadı."
                if not watch:
                    raise CommandError(message) from exc
            if not watch:
                if result.get("issues"):
                    raise CommandError(message)
                self.stdout.write(message)
                return
            time.sleep(max(1, 45 - (time.monotonic() - started)))
