"""Belge klasörlerini anlaşılır adlara dönüştürür; varsayılan yalnızca önizlemedir."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.cases.models import Case, Document
from apps.clients.models import Client, PowerOfAttorney, RetainerAgreement
from apps.core import folders
from apps.core.text import fold


def checked_path(base, path):
    resolved = path.resolve()
    if resolved == base or not resolved.is_relative_to(base) or path.is_symlink():
        raise CommandError("Klasör yolu belge kökünün dışında veya güvenli biçimde taşınamıyor.")
    return path


def plan_group(base, records, parent, label, claimed):
    if not records:
        return []
    changes = []
    occupied = {fold(child.name) for child in parent.iterdir()} if parent.is_dir() else set()
    for record in records:
        name = folders._match_existing(parent, folders.sanitize(record.folder_name))
        source = checked_path(base, parent / name)
        if label == "case" and fold(name) in {fold(folders.POA_DIR), fold(folders.RETAINER_DIR)}:
            raise CommandError(
                "Dosya klasörü vekalet veya sözleşme klasörüyle ortak; işlem durduruldu."
            )
        key = fold(str(source))
        if key in claimed:
            raise CommandError(
                "Aynı klasöre bağlı birden fazla kayıt var; hiçbir klasör taşınmadı."
            )
        claimed.add(key)
        if source.exists() and not source.is_dir():
            raise CommandError("Kayıtlı klasör yolunda başka bir dosya var; işlem durduruldu.")
        wanted = record.name if label == "client" else record.display_name
        if label == "case" and fold(folders.sanitize(wanted)) in {
            fold(folders.POA_DIR),
            fold(folders.RETAINER_DIR),
        }:
            wanted += " (Dosya)"
        # Kendi mevcut adı dışındaki bütün klasörler korunur.
        candidate = (
            name
            if fold(folders.sanitize(wanted)) == fold(name)
            else folders.available_name(wanted, occupied - {fold(name)})
        )
        target = checked_path(base, parent / candidate)
        occupied.add(fold(candidate))
        if source != target:
            changes.append((record, source, target))
    return changes


class Command(BaseCommand):
    help = "Müvekkil ve dosya klasörlerini adlarına göre düzenler; --apply ile uygular."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Önizlenen değişiklikleri uygula.")

    def handle(self, *args, **options):
        base = folders.root()
        if base is None or not base.is_absolute():
            raise CommandError("Ofis belge klasörü ayarlı değil veya tam yol değil.")
        base = base.resolve()
        moved = []
        try:
            with transaction.atomic():
                cases = list(
                    Case.objects.select_for_update().exclude(folder_name="").order_by("pk")
                )
                clients = list(
                    Client.objects.select_for_update().exclude(folder_name="").order_by("pk")
                )
                parent = base / folders.CLIENTS_DIR
                claimed = set()
                client_changes = plan_group(base, clients, parent, "client", claimed)
                case_changes = []
                for owner in clients:
                    owner_dir = checked_path(
                        base,
                        parent
                        / folders._match_existing(parent, folders.sanitize(owner.folder_name)),
                    )
                    case_changes.extend(
                        plan_group(
                            base,
                            [case for case in cases if case.client_id == owner.pk],
                            owner_dir,
                            "case",
                            claimed,
                        )
                    )
                if any(case.client_id not in {owner.pk for owner in clients} for case in cases):
                    raise CommandError("Dosyanın müvekkil klasörü kayıtlı değil; işlem durduruldu.")
                changes = case_changes + client_changes
                updates = []
                for model in (Document, PowerOfAttorney, RetainerAgreement):
                    for item in model.objects.select_for_update().exclude(folder_path=""):
                        path = Path(item.folder_path)
                        for _record, source, target in changes:
                            if path.is_relative_to(source):
                                path = target / path.relative_to(source)
                        if str(path) != item.folder_path:
                            if len(str(path)) > model._meta.get_field("folder_path").max_length:
                                raise CommandError("Yeni belge yolu çok uzun; işlem durduruldu.")
                            updates.append((item, str(path)))
                self.stdout.write(
                    f"{len(client_changes)} müvekkil, {len(case_changes)} dosya klasörü; "
                    f"{len(updates)} belge yolu güncellenecek; "
                    f"{sum(not source.exists() for _, source, _ in changes)} klasör diskte yok."
                )
                if not options["apply"]:
                    self.stdout.write("Önizleme: hiçbir klasör veya kayıt değiştirilmedi.")
                    return
                for record, source, target in changes:
                    checked_path(base, source)
                    checked_path(base, target)
                    if target.exists():
                        raise CommandError("Hedef klasör artık dolu; işlem geri alınıyor.")
                    if source.exists():
                        source.rename(target)
                        moved.append((source, target))
                    type(record).objects.filter(pk=record.pk).update(folder_name=target.name)
                for item, path in updates:
                    type(item).objects.filter(pk=item.pk).update(folder_path=path)
        except Exception as error:
            for source, target in reversed(moved):
                try:
                    checked_path(base, target)
                    checked_path(base, source)
                    target.rename(source)
                except OSError as rollback_error:
                    raise CommandError(
                        "Klasör geri alınamadı; elle kontrol gerekiyor."
                    ) from rollback_error
            if isinstance(error, (CommandError, folders.FolderError)):
                raise CommandError(str(error)) from error
            raise CommandError("Dönüştürme başarısız; klasörler eski yerlerine alındı.") from error
        self.stdout.write("Klasör adları ve belge yolları güncellendi.")
