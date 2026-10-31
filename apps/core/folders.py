"""Ofis klasörüne belge kopyalama.

Yapı:  <Ofis klasörü>\\Müvekkiller\\<Müvekkil>\\<Arşiv no - Konu>\\<belge>
       <Ofis klasörü>\\Müvekkiller\\<Müvekkil>\\Vekaletler\\<belge>

Sistem belgenin asıl kopyasını kendi deposunda (MEDIA_ROOT) tutar; ofis klasörüne
yazılan kopya personelin Windows Gezgini'nden erişimi içindir. Klasör yazılamazsa
işlem durmaz, FolderError ile uyarı verilir.
"""

import logging
import re
import shutil
from pathlib import Path

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
    """Aynı adlı (büyük/küçük harf ve Türkçe aksan farkı gözetmeksizin) klasör varsa onun adı."""
    key = fold(wanted)
    if parent.is_dir():
        for child in parent.iterdir():
            if child.is_dir() and fold(child.name) == key:
                return child.name
    return wanted


def _ensure(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FolderError(f"Klasör oluşturulamadı: {path} ({e.strerror or e})") from e
    return path


def client_dir(client) -> Path:
    base = root()
    if base is None:
        raise FolderError("Ofis klasörü ayarlanmamış (Ayarlar > Belge klasörü).")
    parent = base / CLIENTS_DIR
    if not client.folder_name:
        client.folder_name = _match_existing(parent, sanitize(client.name))
        type(client).objects.filter(pk=client.pk).update(folder_name=client.folder_name)
    return _ensure(parent / sanitize(client.folder_name))


def case_dir(case) -> Path:
    parent = client_dir(case.client)
    if not case.folder_name:
        wanted = sanitize(f"{case.archive_no} - {case.subject}")
        case.folder_name = _match_existing(parent, wanted)
        type(case).objects.filter(pk=case.pk).update(folder_name=case.folder_name)
    return _ensure(parent / sanitize(case.folder_name))


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
    target = unique_path(
        directory, sanitize(Path(filename).stem, 120) + Path(filename).suffix.lower()
    )
    try:
        field_file.open("rb")
        with open(target, "wb") as out:
            shutil.copyfileobj(field_file, out)
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
