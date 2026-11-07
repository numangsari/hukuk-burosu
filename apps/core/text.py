"""Türkçe metin yardımcıları."""

import re

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


_TITLE_SMALL_WORDS = {"ve", "ile", "veya"}


def tr_title(value) -> str:
    """Tamamı büyük harfli metni ekranda okunaklı yazıma çevirir (Sakarya 2. Asliye Ceza Mahkemesi).

    Saklanan değeri değiştirmez; yalnızca gösterim içindir. Zaten karışık harfli metne (ör. UYAP'tan
    gelen) dokunmaz. Nokta, tire ve eğik çizgiden sonra yeni kelime başlar (A.Ş., D.İş); kesme
    işaretinden sonraki ek küçük kalır (Kaya'nın).
    """
    text = "" if value is None else str(value)
    if not text or text != tr_upper(text):
        return text
    out = []
    for i, char in enumerate(text):
        if not char.isalpha() or i == 0 or not (text[i - 1].isalpha() or text[i - 1] in "'’"):
            out.append(char)
        else:
            out.append(tr_lower(char))
    result = "".join(out)
    words = result.split(" ")
    return " ".join(
        w.lower() if i > 0 and w.lower() in _TITLE_SMALL_WORDS else w for i, w in enumerate(words)
    )


_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def tr_lower(value: str) -> str:
    return (value or "").translate(_TR_LOWER).lower()


def fold(value: str) -> str:
    """Büyük/küçük harf ve Türkçe aksan farkını yok sayan karşılaştırma anahtarı."""
    return tr_lower(value).translate(_FOLD).strip()


def poa_reference_number(value: str) -> int | None:
    """V-123 biçimindeki kaynak numarasını, aradaki boşlukları gözetmeden okur."""
    match = re.fullmatch(r"V\s*-\s*([0-9]+)", (value or "").strip(), re.IGNORECASE)
    if not match:
        return None
    digits = match.group(1).lstrip("0")
    if not digits or len(digits) > 10:
        return None
    return int(digits)
