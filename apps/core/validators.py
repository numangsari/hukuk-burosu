"""Türkiye'ye özgü kimlik ve banka numarası doğrulayıcıları."""

import re

from django.core.exceptions import ValidationError


def validate_tckn(value: str) -> None:
    if not re.fullmatch(r"[1-9]\d{10}", value or ""):
        raise ValidationError("TC kimlik no 11 haneli olmalı ve 0 ile başlamamalı.")
    d = [int(c) for c in value]
    tenth = ((sum(d[0:9:2]) * 7) - sum(d[1:8:2])) % 10
    eleventh = sum(d[:10]) % 10
    if d[9] != tenth or d[10] != eleventh:
        raise ValidationError("TC kimlik no geçersiz.")


def validate_vkn(value: str) -> None:
    if not re.fullmatch(r"\d{10}", value or ""):
        raise ValidationError("Vergi kimlik no 10 haneli olmalı.")


def normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def validate_iban(value: str) -> None:
    iban = normalize_iban(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        raise ValidationError("IBAN biçimi geçersiz.")
    if iban.startswith("TR") and len(iban) != 26:
        raise ValidationError("TR IBAN 26 karakter olmalı.")
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    if int(numeric) % 97 != 1:
        raise ValidationError("IBAN kontrol hanesi geçersiz.")
