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
