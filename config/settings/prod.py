from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = 60
# Ofis içi ağda HTTP ile çalışır; HTTPS zorunlu tutulmaz.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": env.path("LOG_FILE", default=BASE_DIR / "logs" / "app.log"),  # noqa: F405
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
        }
    },
    "root": {"handlers": ["file"], "level": "WARNING"},
}
