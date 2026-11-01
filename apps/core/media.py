"""Yüklenen dosyaların yetki kontrolüyle sunulması (/media/...).

Her dosya bağlı olduğu kaydın kuralıyla açılır:
- cases/, tasks/, clients/, avatars/ : giriş yapmış kullanıcı (herkes tüm kayıtları görür)
- ledger/                           : muhasebe görme yetkisi
- office/                           : ofis logosu, giriş ekranında da görünür (girişsiz)
- diğer her yol (ör. imports/tmp)   : sunulmaz
Dosyanın gerçekten bir kayda ait olması da kontrol edilir; sahipsiz dosya sunulmaz.
PDF/resim tarayıcıda açılır, diğerleri indirme olarak verilir.
"""

import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.utils._os import safe_join

from .uploads import INLINE_TYPES


def _record_exists(path: str) -> bool:
    from apps.accounting.models import LedgerEntry
    from apps.accounts.models import User
    from apps.cases.models import Document
    from apps.clients.models import PowerOfAttorney, RetainerAgreement
    from apps.office.models import OfficeSettings
    from apps.tasks.models import TaskDocument

    owners = {
        "cases": (Document, "file"),
        "tasks": (TaskDocument, "file"),
        "clients": (PowerOfAttorney, "pdf"),
        "ledger": (LedgerEntry, "receipt"),
        "avatars": (User, "avatar"),
        "office": (OfficeSettings, "logo"),
    }
    prefix = path.split("/", 1)[0]
    model, field = owners[prefix]
    if prefix == "clients" and "/sozlesme/" in path:
        model = RetainerAgreement
    return model.objects.filter(**{field: path}).exists()


def _allowed(request, prefix: str) -> bool:
    if prefix == "office":
        return True
    if not request.user.is_authenticated:
        return False
    if prefix == "ledger":
        from apps.accounting.permissions import can_view

        return can_view(request.user)
    return prefix in {"cases", "tasks", "clients", "avatars"}


@login_not_required  # yetki aşağıda yol bazında denetlenir (logo girişsiz görünür)
def protected_media(request, path):
    path = path.replace("\\", "/").lstrip("/")
    prefix = path.split("/", 1)[0]
    if prefix not in {"cases", "tasks", "clients", "ledger", "avatars", "office"}:
        raise Http404
    if not _allowed(request, prefix):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        raise PermissionDenied
    try:
        full = Path(safe_join(settings.MEDIA_ROOT, path))
    except Exception as e:  # yol dışına çıkma denemesi
        raise Http404 from e
    if not full.is_file() or not _record_exists(path):
        raise Http404
    ext = full.suffix.lower()
    inline_type = INLINE_TYPES.get(ext)
    resp = FileResponse(
        open(full, "rb"),  # noqa: SIM115 (FileResponse dosyayı kendisi kapatır)
        as_attachment=inline_type is None,
        filename=full.name,
        content_type=inline_type
        or mimetypes.guess_type(full.name)[0]
        or "application/octet-stream",
    )
    resp["X-Content-Type-Options"] = "nosniff"
    if ext != ".pdf":  # Chrome'un PDF görüntüleyicisi sandbox içinde çalışmaz
        resp["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    resp["Cache-Control"] = "private, max-age=0"
    return resp
