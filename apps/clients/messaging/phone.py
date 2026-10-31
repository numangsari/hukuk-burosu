"""Kayıtlı telefonları WhatsApp'ın beklediği uluslararası biçime dönüştürür."""

import re

from django.core.exceptions import ValidationError


def normalize_phone(value, *, international=False):
    text = str(value or "").strip()
    if not re.fullmatch(r"\+?[0-9() .\-]+", text):
        raise ValidationError(
            "Tek bir telefon numarası girin; dahili numara veya açıklama eklemeyin."
        )
    digits = re.sub(r"[^0-9]", "", text)
    explicit = text.startswith("+") or digits.startswith("00")
    if digits.startswith("00"):
        digits = digits[2:]
    if not explicit and not international:
        if len(digits) == 11 and digits.startswith("0"):
            digits = "90" + digits[1:]
        elif len(digits) == 10 and digits[0] in "23458":
            digits = "90" + digits
        elif not (len(digits) == 12 and digits.startswith("90")):
            raise ValidationError("Yurt dışı numarasını + ülke koduyla girin.")
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise ValidationError("Telefon numarası geçerli uzunlukta değil.")
    if digits.startswith("90") and (len(digits) != 12 or digits[2] not in "23458"):
        raise ValidationError("Türkiye numarası ülke kodundan sonra 10 rakam içermeli.")
    return digits
