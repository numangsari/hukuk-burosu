from django.core.management.base import BaseCommand

from apps.imports.models import PortalCase
from apps.imports.portal_finance import import_finance


class Command(BaseCommand):
    help = (
        "UYAP tahsilat/reddiyat verisinden muhasebe hareketlerini hesaplar. "
        "Varsayılan önizlemedir; --apply ile yazar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Hareketleri gerçekten yaz.")
        parser.add_argument("--no", help="Yalnızca bu dosya numarası (örn. 2026/33950).")

    def handle(self, *args, **options):
        apply = options["apply"]
        records = PortalCase.objects.all().order_by("pk")
        if options["no"]:
            records = records.filter(number=options["no"])
        total = 0
        for record in records:
            result = import_finance(record, dry_run=not apply)
            if not (result["satirlar"] or result["notlar"]):
                continue
            self.stdout.write(f"\n== {record.authority} {record.number} (kayıt {record.pk})")
            for state, kind, amount, day, description in result["satirlar"]:
                self.stdout.write(f"  [{state}] {kind:9} {amount:>12} {day}  {description}")
            for note in result["notlar"]:
                self.stdout.write(f"  [atlandı] {note}")
            total += result["yazilan"]
        self.stdout.write(
            f"\n{'Yazılan' if apply else 'Önizleme (yazılmadı)'}: {total if apply else 'bkz. [yeni] satırları'}"
        )
