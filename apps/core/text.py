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
# Büyük harf kalması gereken kısaltmalar (noktalama çıkarıldıktan sonra karşılaştırılır).
_TITLE_ACRONYMS = {
    "UYAP", "UETS", "SGK", "TCK", "CMK", "HMK", "İİK", "TBK", "TMK", "TTK", "KDV", "TC", "PTT",
    "SMMM", "TİB",
}  # fmt: skip


def _title_word(word: str) -> str:
    letters = [c for c in word if c.isalpha()]
    core = "".join(c for c in word if c.isalnum())
    if len(letters) < 2 or word != tr_upper(word) or core in _TITLE_ACRONYMS:
        return word
    out = []
    for i, char in enumerate(word):
        if not char.isalpha() or i == 0 or not (word[i - 1].isalpha() or word[i - 1] in "'’"):
            out.append(char)
        else:
            out.append(tr_lower(char))
    return "".join(out)


def tr_title(value) -> str:
    """Büyük harfli kelimeleri ekranda okunaklı yazıma çevirir (Sakarya 2. Asliye Ceza Mahkemesi).

    Saklanan değeri değiştirmez; yalnızca gösterim içindir. Karışık harfli kelimelere, tek harfe ve
    kısaltmalara (UYAP, SGK...) dokunmaz. Nokta, tire ve eğik çizgiden sonra yeni kelime başlar
    (A.Ş., D.İş); kesme işaretinden sonraki ek küçük kalır (Kaya'nın).
    """
    text = "" if value is None else str(value)
    words = [_title_word(w) for w in text.split(" ")]
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
