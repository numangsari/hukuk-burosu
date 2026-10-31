"""Türkçe metin yardımcıları."""

_TR_LOWER = str.maketrans({"I": "ı", "İ": "i"})
_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def tr_lower(value: str) -> str:
    return (value or "").translate(_TR_LOWER).lower()


def fold(value: str) -> str:
    """Büyük/küçük harf ve Türkçe aksan farkını yok sayan karşılaştırma anahtarı."""
    return tr_lower(value).translate(_FOLD).strip()
