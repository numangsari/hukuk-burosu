from .base import *  # noqa: F403
from .base import env

DEBUG = True
# Statik dosyaları runserver yerine WhiteNoise sunar: DEBUG'da max-age=0 gönderir,
# tarayıcı CSS/JS değişikliğini Ctrl+F5 gerekmeden alır.
INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]  # noqa: F405
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-key")
DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://ozkurt:ozkurt_dev@localhost:5434/ozkurt")
}
