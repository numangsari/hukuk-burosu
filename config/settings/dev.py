from .base import *  # noqa: F403
from .base import env

DEBUG = True
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-key")
DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://ozkurt:ozkurt_dev@localhost:5434/ozkurt")
}
