"""Ortak ayarlar. Ortama özel değerler env değişkenlerinden okunur."""

from pathlib import Path

import environ

from config.hosts import DynamicAllowedHosts

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
# Sabit adresler ortam değişkeninden gelir; yönetici ekranındaki ek adresler dinamik eklenir.
ALLOWED_HOSTS = DynamicAllowedHosts(env.list("DJANGO_ALLOWED_HOSTS", default=["*"]))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
    "django_htmx",
    "auditlog",
    "apps.core",
    "apps.accounts",
    "apps.office",
    "apps.clients",
    "apps.cases",
    "apps.agenda",
    "apps.tasks",
    "apps.accounting",
    "apps.search",
    "apps.activity",
    "apps.reports",
    "apps.backups",
    "apps.imports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.NoStoreMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "apps.accounts.middleware.IdleTimeoutMiddleware",
    "apps.accounts.middleware.ForcePinChangeMiddleware",
    "apps.cases.middleware.SeizureTaskMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.app_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# DATABASES ortama özel dosyalarda tanımlanır (dev.py / prod.py).

AUTH_USER_MODEL = "accounts.User"
# Giriş PIN ile yapılır; PIN kullanıcının parolası olarak hash'li saklanır.
AUTH_PASSWORD_VALIDATORS = [{"NAME": "apps.accounts.validators.PinValidator"}]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Oturum mesai süresince açık kalır, tarayıcı kapanınca biter.
SESSION_COOKIE_AGE = 60 * 60 * 10
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
STATIC_ROOT = env.path("STATIC_ROOT", default=BASE_DIR / "staticfiles")
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUDITLOG_INCLUDE_ALL_MODELS = False

# Django 6 davranışı: şemasız URL https kabul edilir.
FORMS_URLFIELD_ASSUME_HTTPS = True
