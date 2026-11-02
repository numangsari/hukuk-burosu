"""Türkçe metin yardımcıları."""

_TR_LOWER = str.maketrans({"I": "ı", "İ": "i"})
_TR_UPPER = str.maketrans({"i": "İ", "ı": "I"})


def tr_upper(value: str) -> str:
    """Türkçe kurallarla büyük harf (i → İ, ı → I)."""
    return (value or "").translate(_TR_UPPER).upper()


def tr_capitalize_words(value: str) -> str:
    """Her kelimenin ilk harfini Türkçe kurallarla büyütür; diğer harfleri korur."""
    value = value or ""
    return "".join(
        tr_upper(char) if char.isalpha() and (i == 0 or not value[i - 1].isalpha()) else char
        for i, char in enumerate(value)
    )


_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def tr_lower(value: str) -> str:
    return (value or "").translate(_TR_LOWER).lower()


def fold(value: str) -> str:
    """Büyük/küçük harf ve Türkçe aksan farkını yok sayan karşılaştırma anahtarı."""
    return tr_lower(value).translate(_FOLD).strip()
