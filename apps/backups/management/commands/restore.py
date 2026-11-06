from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.backups.models import BackupRecord
from apps.backups.services import BackupError, restore, run_backup


class Command(BaseCommand):
    help = (
        "Yedeği geri yükler. MEVCUT VERİLERİN YERİNE GEÇER. "
        "Önce uygulama servisini durdurun; mevcut belgeler 'media.onceki-...' adıyla saklanır. "
        "Geri yüklemeden önce mevcut verinin tam yedeği otomatik alınır."
    )

    def add_arguments(self, parser):
        parser.add_argument("zip_path")
        parser.add_argument("--yes", action="store_true", help="Onay sormadan geri yükle")
        parser.add_argument(
            "--guvenlik-yedegi-alma",
            action="store_true",
            help="Geri yükleme öncesi otomatik yedeği atla (veritabanı bozuksa)",
        )

    def handle(self, *args, zip_path, yes, guvenlik_yedegi_alma=False, **options):
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
        if not guvenlik_yedegi_alma:
            # Yanlış yedek seçilirse geri dönülebilsin diye mevcut durumun tam yedeği alınır.
            record = run_backup(BackupRecord.Kind.PRE_RESTORE)
            if record.status != BackupRecord.Status.OK:
                raise CommandError(
                    f"Geri yükleme öncesi güvenlik yedeği alınamadı: {record.message} "
                    "Geri yükleme başlatılmadı."
                )
            self.stdout.write(f"Güvenlik yedeği alındı: {record.file_name}")
        try:
            restore(path)
        except BackupError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(
            self.style.SUCCESS("Geri yükleme tamamlandı. Uygulama servisini başlatın.")
        )
