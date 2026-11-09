from django.core.management.base import BaseCommand

from apps.imports.office_enrich import enrich


class Command(BaseCommand):
    help = (
        "Eski ofis listelerindeki karşı taraf, aşama, haciz ve not bilgilerini dosyalara işler. "
        "Varsayılan deneme çalıştırmasıdır; --uygula ile kalıcı yazar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--uygula", action="store_true", help="Değişiklikleri kaydet")

    def handle(self, *args, uygula, **options):
        counts = enrich(apply=uygula)
        mode = "UYGULANDI" if uygula else "DENEME (hiçbir şey kaydedilmedi)"
        self.stdout.write(f"{mode}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
