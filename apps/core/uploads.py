"""Yüklenen dosyalar için ortak kurallar.

Yalnızca ofiste kullanılan belge türleri kabul edilir. Tarayıcıda kod çalıştırabilecek
(HTML, SVG, JS) veya bilgisayarda çalıştırılabilen (EXE, BAT, PS1...) dosyalar reddedilir.
Sunumda yalnızca PDF ve resimler tarayıcıda açılır; diğer her şey indirme olarak verilir.
"""

from pathlib import Path

from django.core.exceptions import ValidationError

MAX_UPLOAD = 50 * 1024 * 1024

DOCUMENT_EXTENSIONS = {
    # belge
    ".pdf", ".udf", ".doc", ".docx", ".odt", ".rtf", ".txt",
    # tablo / sunum
    ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp",
    # resim
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".heic",
    # e-posta ve arşiv
    ".eml", ".msg", ".zip", ".rar", ".7z",
}  # fmt: skip
PDF_OR_IMAGE = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

# Tarayıcıda açılmasında sakınca olmayan türler (MIME türü sunucu tarafından belirlenir).
INLINE_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8",
}


# Dosya imzaları (ilk baytlar): uzantı ile içerik uyuşmuyorsa yükleme reddedilir.
# Yalnızca imzası kesin bilinen türler denetlenir; diğer türler (txt, csv, udf, eml...) için
# uzantı denetimi yeterli sayılır ve bunlar tarayıcıda açılmaz / indirme olarak sunulur.
# `.xls` bilerek denetlenmez: bankalar HTML/CSV içeriği `.xls` adıyla verebilir.
_ZIP = (b"PK\x03\x04", b"PK\x05\x06")
_OLE = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)
SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
    ".docx": _ZIP,
    ".xlsx": _ZIP,
    ".pptx": _ZIP,
    ".odt": _ZIP,
    ".ods": _ZIP,
    ".odp": _ZIP,
    ".zip": _ZIP,
    ".doc": _OLE + _ZIP + (b"{\\rtf",),  # bazı Word sürümleri RTF/OOXML'i .doc kaydeder
    ".ppt": _OLE,
    ".msg": _OLE,
    ".rtf": (b"{\\rtf",),
    ".rar": (b"Rar!\x1a\x07",),
    ".7z": (b"7z\xbc\xaf\x27\x1c",),
}
# PDF imzası, başta çöp bayt bulunan dosyalar için ilk 1024 baytta aranır.
_PDF_WINDOW = 1024


def _matches_signature(f, ext: str) -> bool:
    signatures = SIGNATURES.get(ext)
    if not signatures:
        return True
    try:
        position = f.tell()
    except (AttributeError, OSError):
        position = None
    try:
        head = f.read(_PDF_WINDOW)
    finally:
        if position is not None:
            f.seek(position)
        else:
            f.seek(0)
    if ext == ".pdf":
        return b"%PDF-" in head
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return any(head.startswith(signature) for signature in signatures)


def validate_upload(f, allowed: set[str] = DOCUMENT_EXTENSIONS, max_size: int = MAX_UPLOAD):
    if not f:
        return
    ext = Path(f.name).suffix.lower()
    if ext not in allowed:
        kinds = ", ".join(sorted(e.lstrip(".").upper() for e in allowed))
        raise ValidationError(
            f"Bu dosya türü kabul edilmiyor ({ext or 'uzantısız'}). İzin verilenler: {kinds}."
        )
    if f.size > max_size:
        raise ValidationError(f"Dosya {max_size // (1024 * 1024)} MB'tan büyük olamaz.")
    if not _matches_signature(f, ext):
        raise ValidationError(
            f"Dosya içeriği uzantısıyla ({ext}) uyuşmuyor. Dosya bozuk veya yanlış türde olabilir."
        )
