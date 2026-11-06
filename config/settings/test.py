from .dev import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MEDIA_ROOT = BASE_DIR / ".test-media"  # noqa: F405
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# WhiteNoise, STATIC_ROOT yoksa her istekte uyarı verir; testler collectstatic gerektirmesin.
STATIC_ROOT = BASE_DIR / ".test-static"  # noqa: F405
STATIC_ROOT.mkdir(exist_ok=True)
