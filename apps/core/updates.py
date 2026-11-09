"""Otomatik güncelleyicinin (installer/scripts/updater.ps1) yazdığı durum dosyasını okur.

Güncelleyici her denemeden sonra `data/updates/status.json` dosyasına sonucu yazar. Uygulama bu
dosyayı yalnızca okur; yolu `UPDATE_STATUS_FILE` ayarından gelir (geliştirmede tanımsızdır).
"""

import json
import logging
from pathlib import Path

from django.conf import settings
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

RESULT_LABELS = {
    "ok": "Güncelleme başarılı",
    "downloaded": "Yeni sürüm indirildi; bilgisayar yeniden açılınca kurulacak",
    "rolled_back": "Güncelleme başarısız; önceki sürüme dönüldü",
    "rollback_failed": "Güncelleme başarısız ve önceki sürüme dönülemedi",
}
PROBLEM_RESULTS = {"rolled_back", "rollback_failed"}


def update_status() -> dict | None:
    """Son güncelleme sonucunu döndürür; dosya yoksa veya okunamazsa None."""
    path = getattr(settings, "UPDATE_STATUS_FILE", None)
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("Güncelleme durum dosyası okunamadı: %s", path)
        return None
    if not isinstance(data, dict) or data.get("result") not in RESULT_LABELS:
        return None
    result = data["result"]
    return {
        "result": result,
        "label": RESULT_LABELS[result],
        "problem": result in PROBLEM_RESULTS,
        "version": str(data.get("version", "")),
        "from_version": str(data.get("from_version", "")),
        "at": parse_datetime(str(data.get("at", ""))),
    }
