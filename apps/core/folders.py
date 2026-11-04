"""Ofis klasörüne belge kopyalama.

Yapı:  <Ofis klasörü>\\Müvekkiller\\<Müvekkil adı>\\<Kurum - Dosya numarası>\\<belge>
       <Ofis klasörü>\\Müvekkiller\\<Müvekkil adı>\\Vekaletler\\<belge>

Sistem belgenin asıl kopyasını kendi deposunda (MEDIA_ROOT) tutar; ofis klasörüne
yazılan kopya personelin Windows Gezgini'nden erişimi içindir. Klasör yazılamazsa
işlem durmaz, FolderError ile uyarı verilir.
"""

import logging
import re
import shutil
import tempfile
from pathlib import Path

from django.db import transaction

from apps.core.text import fold

log = logging.getLogger(__name__)

CLIENTS_DIR = "Müvekkiller"
POA_DIR = "Vekaletler"
RETAINER_DIR = "Sözleşmeler"
TASKS_DIR = "Görevler"
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


def available_name(wanted, occupied):
    """Aynı adlı klasörleri birleştirmeden sıradaki boş adı seçer."""
    stem = sanitize(wanted)
    name, number = stem, 2
    while fold(name) in occupied:
        name = f"{stem} ({number})"
        number += 1
    return name


def _record_dir(record, parent, default_name, others, label) -> Path:
    if not record.folder_name:
        occupied = {fold(sanitize(name)) for name in others.values_list("folder_name", flat=True)}
        try:
            if parent.is_dir():
                occupied.update(fold(child.name) for child in parent.iterdir())
        except OSError as e:
            raise FolderError("Belge klasörü okunamadı.") from e
        name = available_name(default_name, occupied)
        _ensure(parent)
        while True:
            try:
                (parent / name).mkdir()
                break
            except FileExistsError:
                occupied.add(fold(name))
                name = available_name(default_name, occupied)
            except OSError as e:
                raise FolderError("Klasör oluşturulamadı.") from e
        type(record).objects.filter(pk=record.pk).update(folder_name=name)
        record.folder_name = name
        return parent / name
    wanted = sanitize(record.folder_name)
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
    if client is None:
        raise FolderError(
            "Dosyanın müvekkili henüz seçilmediği için belge ofis "
            "klasörüne kopyalanmadı (sistemde saklandı)."
        )
    base = root()
    if base is None:
        raise FolderError("Ofis klasörü ayarlanmamış (Ayarlar > Belge klasörü).")
    parent = base / CLIENTS_DIR
    stored = type(client).objects.select_for_update().get(pk=client.pk)
    from apps.office.models import OfficeSettings

    OfficeSettings.objects.select_for_update().get(pk=1)
    others = type(client).objects.exclude(pk=client.pk).exclude(folder_name="")
    path = _record_dir(stored, parent, stored.name, others, "müvekkil")
    client.folder_name = stored.folder_name
    return path


@transaction.atomic
def case_dir(case) -> Path:
    stored = type(case).objects.select_for_update().get(pk=case.pk)
    if stored.client_id is None:
        raise FolderError(
            "Dosyanın müvekkili henüz seçilmediği için belge ofis "
            "klasörüne kopyalanmadı (sistemde saklandı)."
        )
    parent = client_dir(stored.client)
    others = type(case).objects.filter(client_id=stored.client_id).exclude(pk=case.pk)
    others = others.exclude(folder_name="")
    wanted = stored.folder_name or stored.display_name
    if fold(sanitize(wanted)) in {fold(POA_DIR), fold(RETAINER_DIR)}:
        if stored.folder_name:
            raise FolderError("Dosya klasörü için Vekaletler veya Sözleşmeler adı kullanılamaz.")
        wanted += " (Dosya)"
    path = _record_dir(stored, parent, wanted, others, "dosya")
    case.folder_name = stored.folder_name
    return path


def poa_dir(client) -> Path:
    return _ensure(client_dir(client) / POA_DIR)


def retainer_dir(client) -> Path:
    return _ensure(client_dir(client) / RETAINER_DIR)


def task_dir(case) -> Path:
    parent = case_dir(case)
    path = parent / TASKS_DIR
    base = root()
    if path.is_symlink() or base is None or not path.resolve().is_relative_to(base.resolve()):
        raise FolderError("Görev klasörü belge kökünün dışında veya güvenli değil.")
    return _ensure(path)


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
        return "Tam bir klasör yolu girin (ör. D:\\Hukuk Belgeleri)."
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b"ok")
    except OSError as e:
        return f"Klasöre yazılamıyor: {e.strerror or e}"
    return ""
