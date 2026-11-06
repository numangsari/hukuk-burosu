from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.backups.models import BackupRecord
from apps.backups.services import BackupError, restore, run_backup


class Command(BaseCommand):
    help = (
        "Yedeği geri yükler. MEVCUT VERİLERİN YERİNE GEÇER. "
        "Önce mevcut verinin güvenlik yedeği alınır (alınamazsa geri yükleme iptal edilir). "
        "Önce uygulama servisini durdurun; mevcut belgeler 'media.onceki-...' adıyla saklanır."
    )

    def add_arguments(self, parser):
        parser.add_argument("zip_path")
        parser.add_argument("--yes", action="store_true", help="Onay sormadan geri yükle")
        parser.add_argument(
            "--skip-safety-backup",
            action="store_true",
            help="Geri yüklemeden önce mevcut verinin yedeğini alma (önerilmez)",
        )

    def handle(self, *args, zip_path, yes, skip_safety_backup, **options):
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
        if not skip_safety_backup:
            rec = run_backup(BackupRecord.Kind.UPDATE)
            if rec.status != BackupRecord.Status.OK:
                raise CommandError(
                    f"Güvenlik yedeği alınamadı, geri yükleme iptal edildi: {rec.message}"
                )
            self.stdout.write(f"Güvenlik yedeği alındı: {rec.file_name}")
        try:
            restore(path)
        except BackupError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(
            self.style.SUCCESS("Geri yükleme tamamlandı. Uygulama servisini başlatın.")
        )
