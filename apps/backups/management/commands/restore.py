from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.backups.services import BackupError, restore


class Command(BaseCommand):
    help = (
        "Şifreli yedeği geri yükler. MEVCUT VERİLERİN YERİNE GEÇER. "
        "Önce uygulama servisini durdurun; mevcut belgeler 'media.onceki-...' adıyla saklanır."
    )

    def add_arguments(self, parser):
        parser.add_argument("zip_path")
        parser.add_argument("--yes", action="store_true", help="Onay sormadan geri yükle")

    def handle(self, *args, zip_path, yes, **options):
        path = Path(zip_path)
        if not path.is_file():
            raise CommandError(f"Dosya bulunamadı: {path}")
        if not yes:
            answer = input(
                f"{path.name} geri yüklenecek, mevcut veriler değişecek. Devam? (evet/hayır): "
            )
            if answer.strip().lower() != "evet":
                self.stdout.write("İptal edildi.")
                return
        try:
            restore(path)
        except BackupError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(
            self.style.SUCCESS("Geri yükleme tamamlandı. Uygulama servisini başlatın.")
        )
