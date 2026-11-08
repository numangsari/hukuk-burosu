"""Uygulama sürümü: tek kaynak `pyproject.toml` içindeki `version` alanıdır.

Kurulum paketi derlenirken aynı değer uygulama klasörüne `VERSION` dosyası olarak yazılır.
"""

import tomllib
from functools import cache

from django.conf import settings

PRODUCT_NAME = "Hukuk Bürosu Otomasyonu"


@cache
def app_version() -> str:
    base = settings.BASE_DIR
    try:
        return (base / "VERSION").read_text(encoding="utf-8-sig").strip() or "?"
    except OSError:
        pass
    try:
        with (base / "pyproject.toml").open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "?"
