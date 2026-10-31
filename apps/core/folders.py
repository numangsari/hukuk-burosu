"""Ofis klasörüne belge kopyalama.

Yapı:  <Ofis klasörü>\\Müvekkiller\\<M000142 - Müvekkil>\\<D000041 - Arşiv no - Konu>\\<belge>
       <Ofis klasörü>\\Müvekkiller\\<M000142 - Müvekkil>\\Vekaletler\\<belge>

Sistem belgenin asıl kopyasını kendi deposunda (MEDIA_ROOT) tutar; ofis klasörüne
yazılan kopya personelin Windows Gezgini'nden erişimi içindir. Klasör yazılamazsa
işlem durmaz, FolderError ile uyarı verilir.
"""

import logging
import re
import shutil
from pathlib import Path

from django.db import transaction

from apps.core.text import fold

log = logging.getLogger(__name__)

CLIENTS_DIR = "Müvekkiller"
POA_DIR = "Vekaletler"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class FolderError(Exception):
    pass


def sanitize(name: str, max_len: int = 80) -> str:
    """Windows'ta geçerli klasör/dosya adı."""
    name = _INVALID.sub("-", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    name = name[:max_len].rstrip(". ") or "Adsız"
    if name.upper() in _RESERVED:
        name += "_"
    return name


def root() -> Path | None:
    from apps.office.models import OfficeSettings

    value = (OfficeSettings.load().documents_root or "").strip()
    return Path(value) if value else None


def _match_existing(parent: Path, wanted: str) -> str:
    """Kaydedilmiş klasör adını diskte bulur; birden fazla eşleşmede seçim yapmaz."""
    key = fold(wanted)
    try:
        matches = (
            [child.name for child in parent.iterdir() if child.is_dir() and fold(child.name) == key]
            if parent.is_dir()
            else []
        )
    except OSError as e:
        raise FolderError("Belge klasörü okunamadı.") from e
    if len(matches) > 1:
        raise FolderError("Benzer adla birden fazla klasör var. Kayıttaki klasör adını ayırın.")
    return matches[0] if matches else wanted


def _ensure(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FolderError(f"Klasör oluşturulamadı: {path} ({e.strerror or e})") from e
    return path


def _record_dir(record, parent, default_name, others, label) -> Path:
    wanted = sanitize(record.folder_name or default_name)
    key = fold(wanted)
    if any(fold(sanitize(name)) == key for name in others.values_list("folder_name", flat=True)):
        raise FolderError(
            f"Bu klasör başka bir {label} kaydına da bağlı. "
            "Belge kaydedildi; klasöre kopyalamak için kayıtlardaki klasör adlarını ayırın."
        )
    name = _match_existing(parent, wanted)
    path = _ensure(parent / name)
    if record.folder_name != name:
        type(record).objects.filter(pk=record.pk).update(folder_name=name)
        record.folder_name = name
    return path


@transaction.atomic
def client_dir(client) -> Path:
    base = root()
    if base is None:
        raise FolderError("Ofis klasörü ayarlanmamış (Ayarlar > Belge klasörü).")
    parent = base / CLIENTS_DIR
    stored = type(client).objects.select_for_update().get(pk=client.pk)
    others = type(client).objects.exclude(pk=client.pk).exclude(folder_name="")
    path = _record_dir(stored, parent, f"M{stored.pk:06d} - {stored.name}", others, "müvekkil")
    client.folder_name = stored.folder_name
    return path


@transaction.atomic
def case_dir(case) -> Path:
    stored = type(case).objects.select_for_update().get(pk=case.pk)
    parent = client_dir(stored.client)
    others = type(case).objects.filter(client_id=stored.client_id).exclude(pk=case.pk)
    others = others.exclude(folder_name="")
    if stored.folder_name and fold(sanitize(stored.folder_name)) == fold(POA_DIR):
        raise FolderError("Dosya klasörü için Vekaletler adı kullanılamaz. Farklı bir ad seçin.")
    wanted = f"D{stored.pk:06d} - {stored.archive_no} - {stored.subject}"
    path = _record_dir(stored, parent, wanted, others, "dosya")
    case.folder_name = stored.folder_name
    return path


def poa_dir(client) -> Path:
    return _ensure(client_dir(client) / POA_DIR)


def unique_path(directory: Path, filename: str) -> Path:
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate, n = directory / f"{stem}{suffix}", 2
    while candidate.exists():
        candidate = directory / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


def copy_file(field_file, directory: Path, filename: str) -> Path:
    """Django FieldFile'ı klasöre kopyalar; aynı ad varsa sonuna (2), (3)... ekler."""
    filename = sanitize(Path(filename).stem, 120) + Path(filename).suffix.lower()
    target = directory / filename
    try:
        field_file.open("rb")
        while True:
            target = unique_path(directory, filename)
            try:
                with open(target, "xb") as out:
                    shutil.copyfileobj(field_file, out)
                break
            except FileExistsError:
                continue
    except OSError as e:
        raise FolderError(f"Belge klasöre yazılamadı: {target} ({e.strerror or e})") from e
    finally:
        field_file.close()
    return target


def check_writable(path_str: str) -> str:
    """Ayarlar ekranı için: klasör yoksa oluşturur, yazılabilir mi dener. Hata metni döner."""
    path = Path(path_str)
    if not path.is_absolute():
        return "Tam bir klasör yolu girin (ör. D:\\Ozkurt Hukuk Ofis)."
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".yazma-testi"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return f"Klasöre yazılamıyor: {e.strerror or e}"
    return ""
