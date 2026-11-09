from pathlib import Path

from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = 60
# Ofis içi ağda HTTP ile çalışır; HTTPS zorunlu tutulmaz. Sistem dışarıya açılırsa
# (ör. VPN dışında internet) önce HTTPS kurulmalı ve bu susturmalar kaldırılmalıdır.
SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W008", "security.W012", "security.W016"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Otomatik güncelleyicinin (tools\updater.ps1) son sonucu; Ayarlar > Hakkında'da gösterilir.
UPDATE_STATUS_FILE = env.path(
    "UPDATE_STATUS_FILE",
    default=BASE_DIR.parent / "data" / "updates" / "status.json",  # noqa: F405
)
LOG_FILE = env.path("LOG_FILE", default=BASE_DIR / "logs" / "app.log")  # noqa: F405
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_FILE),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
        }
    },
    "root": {"handlers": ["file"], "level": "WARNING"},
}
