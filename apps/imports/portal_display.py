"""Dosyaya bağlı UYAP bilgilerini, ofis kayıtlarına dokunmadan hazırlar."""

import re
from datetime import date, datetime


def _value(value):
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "Evet" if value else "Hayır"
    if isinstance(value, dict):
        parts = value.get("date", value)
        if isinstance(parts, dict):
            try:
                return date(int(parts["year"]), int(parts["month"]), int(parts["day"])).strftime(
                    "%d.%m.%Y"
                )
            except (KeyError, TypeError, ValueError):
                return ""
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _date_value(value):
    text = _value(value)
    if not text:
        return ""
    english_date = re.match(
        r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4})",
        text,
    )
    if english_date:
        months = (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        )
        try:
            formatted = date(
                int(english_date[3]), months.index(english_date[1]) + 1, int(english_date[2])
            ).strftime("%d.%m.%Y")
            time_match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)$", text)
            if time_match:
                hour = int(time_match[1]) % 12 + (12 if time_match[4] == "PM" else 0)
                formatted += f" {hour:02d}:{time_match[2]}"
                if time_match[3] and time_match[3] != "00":
                    formatted += f":{time_match[3]}"
            return formatted
        except ValueError:
            return text
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return text


def case_information(record):
    """Kaynak bilgilerini alan bazında birleştirir; eksik yeni yanıt eski bilgiyi silmez."""
    if record is None or not isinstance(record.data, dict):
        return None
    data = record.data
    row = data.get("liste") if isinstance(data.get("liste"), dict) else {}
    details = {}
    detail_rows = data.get("ayrintilar")
    for item in detail_rows if isinstance(detail_rows, list) else []:
        if isinstance(item, dict):
            for key, value in item.items():
                if _value(value):
                    details[key] = value

    definitions = [
        ("Kurum", (row.get("birimAdi"), record.authority)),
        ("Dosya numarası", (row.get("dosyaNo"), record.number)),
        ("Dosya türü", (row.get("dosyaTur"), row.get("dosyaTurKodAciklama"), record.category)),
        ("Durum", (details.get("dosyaDurumu"), row.get("dosyaDurum"), record.status)),
        ("Açılış tarihi", (details.get("dosyaAcilisTarihi"), row.get("dosyaAcilisTarihi"))),
        ("Açılış türü", (details.get("davaAcilisTuruStr"),)),
        (
            "Konu",
            (
                details.get("davaTurleriStr"),
                details.get("davaninKonusu"),
                details.get("davaKonusu"),
            ),
        ),
        ("Duruşma tarihi", (details.get("durusmaTarihiStr"), details.get("durusmaTarihi"))),
        ("Ön inceleme tarihi", (details.get("onIncelemTarihiStr"), details.get("onIncelemTarihi"))),
        ("Takibin türü", (details.get("takibinTuruAciklama"),)),
        ("Takibin şekli", (details.get("takibinSekliAciklama"),)),
        ("Takibin yolu", (details.get("takibinYoluAciklama"),)),
        ("Yürütmenin durdurulması", (details.get("ydli"),)),
        ("Karar numarası", (details.get("kararNo"),)),
        ("Karar tarihi", (details.get("kararTarihi"),)),
        ("Karar", (details.get("karar"), details.get("kararAciklama"))),
        ("Kapanış tarihi", (details.get("dosyaKapanisTarihi"), details.get("kapanisTarihi"))),
        ("Kapanış nedeni", (details.get("kapanisSebebi"),)),
        ("Arabulucu", (details.get("arabulucu"),)),
        ("Gelen kurum", (details.get("gelenBirimAdi"),)),
        ("Gelen dosya numarası", (details.get("gelenDosyaNo"),)),
    ]
    fields = []
    date_labels = {
        "Açılış tarihi",
        "Duruşma tarihi",
        "Ön inceleme tarihi",
        "Karar tarihi",
        "Kapanış tarihi",
    }
    for label, candidates in definitions:
        convert = _date_value if label in date_labels else _value
        value = next((text for value in candidates if (text := convert(value))), "")
        if value:
            fields.append((label, value))

    account = []
    accounts = data.get("hesaplar")
    for item in reversed(accounts if isinstance(accounts, list) else []):
        if isinstance(item, list) and item:
            account = [
                (str(x.get("textAlan") or "").strip(), _value(x.get("degerAlan")))
                for x in item
                if isinstance(x, dict) and x.get("textAlan") and _value(x.get("degerAlan"))
            ]
            if account:
                break
    return {"fields": fields, "account": account}
