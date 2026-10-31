import re

from django.core.exceptions import ValidationError


class PinValidator:
    """PIN yalnızca rakamdan oluşur ve 4-8 hanelidir."""

    def validate(self, password, user=None):
        if not re.fullmatch(r"\d{4,8}", password or ""):
            raise ValidationError("PIN 4-8 haneli ve yalnızca rakam olmalı.", code="invalid_pin")

    def get_help_text(self):
        return "PIN 4-8 haneli ve yalnızca rakam olmalı."
