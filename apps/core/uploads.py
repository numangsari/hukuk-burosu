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


ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")  # docx, xlsx, pptx, odf, udf, zip
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # doc, xls, ppt, msg (eski Office)

# Uzantıya göre beklenen dosya başlığı (magic bytes). Burada olmayan türler (txt, csv, eml,
# rtf, heic, gif dışındaki metin tabanlı belgeler) içerik denetimine tabi tutulmaz.
SIGNATURES = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
    ".doc": (OLE_SIGNATURE,),
    ".xls": (OLE_SIGNATURE,),
    ".ppt": (OLE_SIGNATURE,),
    ".msg": (OLE_SIGNATURE,),
    ".docx": ZIP_SIGNATURES,
    ".xlsx": ZIP_SIGNATURES,
    ".pptx": ZIP_SIGNATURES,
    ".odt": ZIP_SIGNATURES,
    ".ods": ZIP_SIGNATURES,
    ".odp": ZIP_SIGNATURES,
    ".udf": ZIP_SIGNATURES,
    ".zip": ZIP_SIGNATURES,
    ".rar": (b"Rar!\x1a\x07",),
    ".7z": (b"7z\xbc\xaf\x27\x1c",),
}


def _matches_signature(head: bytes, ext: str) -> bool:
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    expected = SIGNATURES.get(ext)
    if expected is None:
        return True
    return any(head.startswith(sig) for sig in expected)


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
    if ext in SIGNATURES or ext == ".webp":
        f.seek(0)
        head = f.read(16)
        f.seek(0)
        if not _matches_signature(head, ext):
            raise ValidationError(
                f"Dosyanın içeriği {ext.upper()} türüyle uyuşmuyor. "
                "Dosyayı kontrol edip yeniden yükleyin."
            )
