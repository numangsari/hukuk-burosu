import re

from django.core.exceptions import ValidationError


class PinValidator:
    """PIN tam 4 rakamdır (giriş ekranı 4. rakamda otomatik gönderir)."""

    def validate(self, password, user=None):
        if not re.fullmatch(r"\d{4}", password or ""):
            raise ValidationError("PIN 4 haneli ve yalnızca rakam olmalı.", code="invalid_pin")

    def get_help_text(self):
        return "PIN 4 haneli ve yalnızca rakam olmalı."
