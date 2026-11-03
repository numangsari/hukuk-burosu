"""Dosyaya bağlı UYAP bilgilerini hazırlar ve ayrıştırır."""

import re
from datetime import date, datetime

from apps.core.text import fold


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
    for pattern in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, pattern)
            if "%H" in pattern and (dt.hour or dt.minute):
                return dt.strftime("%d.%m.%Y %H:%M")
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            continue
    return text


def merged_details(record) -> dict:
    """PortalCase içindeki tüm ayrıntı yanıtlarını tek sözlükte birleştirir."""
    if record is None or not isinstance(record.data, dict):
        return {}
    details = {}
    detail_rows = record.data.get("ayrintilar")
    for item in detail_rows if isinstance(detail_rows, list) else []:
        if isinstance(item, dict):
            for key, value in item.items():
                if value not in (None, "", []):
                    details[key] = value
    return details


def uyap_subject_value(record) -> str:
    """Dava türleri ile dava açılış türünü yan yana ('UYAP Dava Konusu') birleştirir."""
    if record is None or not isinstance(record.data, dict):
        return ""
    details = merged_details(record)
    subject = (
        _value(details.get("davaTurleriStr"))
        or _value(details.get("davaninKonusu"))
        or _value(details.get("davaKonusu"))
    )
    if not subject and isinstance(details.get("davaTurList"), list):
        items = []
        for item in details["davaTurList"]:
            if isinstance(item, dict):
                parts = [
                    _value(item.get("aciklamasi")),
                    _value(item.get("bagliOlduguDavaTuruAciklamasi")),
                ]
                joined = " - ".join(p for p in parts if p)
                if joined and joined not in items:
                    items.append(joined)
        subject = ", ".join(items)
    opening_kind = _value(details.get("davaAcilisTuruStr"))
    if subject and opening_kind:
        return f"{subject} · {opening_kind}"
    return subject or opening_kind


def uyap_stage_value(record) -> str:
    """UYAP'taki aşama veya kapanış nedenini döndürür."""
    if record is None or not isinstance(record.data, dict):
        return ""
    row = record.data.get("liste") if isinstance(record.data.get("liste"), dict) else {}
    details = merged_details(record)
    raw_status = _value(row.get("dosyaDurum")) or _value(record.status)
    detail_status = _value(details.get("dosyaDurumu"))
    decision_note = _value(details.get("kararAciklama")) or _value(details.get("karar"))

    is_closed = (
        row.get("dosyaDurumKod") == 1
        or fold(raw_status).startswith("kapali")
        or fold(detail_status).startswith("kapali")
    )
    if is_closed:
        match = re.search(r"Kapalı\s*\(([^0-9\)]+)\)", raw_status, re.I)
        if match:
            return match.group(1).strip()
        if detail_status and not fold(detail_status).startswith("kapali"):
            return detail_status
        if decision_note:
            return decision_note
        return "Kapalı"
    if raw_status and fold(raw_status) not in {"acik"}:
        return raw_status
    if detail_status and fold(detail_status) not in {"acik", "kapali"}:
        return detail_status
    return raw_status or detail_status or "Açık"


def next_hearing_value(record) -> str:
    """Sıradaki (veya son) duruşma / ön inceleme tarih ve saatini döndürür."""
    if record is None or not isinstance(record.data, dict):
        return ""
    details = merged_details(record)
    candidates = []
    if details.get("onIncelemTarihiStr") or details.get("onIncelemTarihi"):
        val = _date_value(details.get("onIncelemTarihiStr") or details.get("onIncelemTarihi"))
        if val:
            candidates.append(f"{val} (Ön İnceleme)")
    if details.get("durusmaTarihiStr") or details.get("durusmaTarihi"):
        val = _date_value(details.get("durusmaTarihiStr") or details.get("durusmaTarihi"))
        if val:
            candidates.append(val)
    for hearing in record.data.get("durusmalar") or []:
        if not isinstance(hearing, dict):
            continue
        val = _date_value(hearing.get("tarihSaat"))
        kind = _value(hearing.get("islemTuruAciklama"))
        if val:
            label = f"{val} ({kind})" if kind and fold(kind) != "durusma" else val
            if label not in candidates:
                candidates.append(label)
    return candidates[-1] if candidates else ""


def _guess_case_type(authority: str) -> str:
    text = fold(authority)
    if "icra" in text:
        return "enforcement"
    if "arabuluc" in text:
        return "mediation"
    if "satis" in text:
        return "sales_office"
    if "savci" in text or "sorusturma" in text or "cbs" in text:
        return "investigation"
    if "ceza" in text:
        return "criminal"
    if "idare" in text or "vergi" in text or "danistay" in text or "bolge idare" in text:
        return "administrative"
    return "civil"


def extract_related_cases(record) -> list[dict]:
    """UYAP ayrıntılarında geçen ilgili/birleşen/gelen dosyaları ayrıştırır."""
    if record is None or not isinstance(record.data, dict):
        return []
    details = merged_details(record)
    items = []
    seen = set()

    def add_item(authority, number, relation):
        authority = " ".join(str(authority or "").split()).strip(" -–—:")
        number = str(number or "").replace(" ", "").strip()
        if not authority or not number or number == "/":
            return
        key = (fold(authority), number)
        if key in seen:
            return
        seen.add(key)
        items.append(
            {
                "authority": authority,
                "number": number,
                "relation": relation,
                "case_type": _guess_case_type(authority),
            }
        )

    if details.get("gelenBirimAdi") and details.get("gelenDosyaNo"):
        add_item(details.get("gelenBirimAdi"), details.get("gelenDosyaNo"), "Gelen dosya")

    for field, relation in (
        ("ilgiliDosyaListesiStr", "İlgili dosya"),
        ("ilgiliDavaListesiStr", "İlgili dava"),
        ("ilgiliSeriDavaListesiStr", "İlgili seri dava"),
        ("birlesenDosyaListStr", "Birleşen dosya"),
    ):
        raw = _value(details.get(field))
        if not raw:
            continue
        for part in re.split(r"[,;\n]+", raw):
            part = part.strip()
            match = re.search(r"^(.+?)\s+(\d{4}\s*/\s*\d+)\b", part)
            if match:
                add_item(match.group(1), match.group(2), relation)

    return items


def account_items(record) -> list[tuple[str, str]]:
    """İcra Dosya Hesabı sekmesi için hesap kalemlerini döndürür."""
    if record is None or not isinstance(record.data, dict):
        return []
    data = record.data
    account = []
    seen = set()
    accounts = data.get("hesaplar")
    for item in reversed(accounts if isinstance(accounts, list) else []):
        if isinstance(item, list) and item:
            for row in item:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("textAlan") or "").strip()
                val = _value(row.get("degerAlan"))
                if label and val != "":
                    account.append(
                        (label, f"{val} ₺" if re.match(r"^-?\d+(\.\d+)?$", val) else val)
                    )
                    seen.add(fold(label))
            if account:
                break

    details = merged_details(record)
    extra_labels = (
        ("alacakKalemToplamTutar", "Alacak kalemleri toplamı"),
        ("alacakKalemFaizTutar", "Alacak kalemi faiz tutarı"),
        ("tahsilHarci", "Tahsil harcı"),
        ("takipSonrasiMasraf", "Takip sonrası masraf"),
        ("vekaletUcreti", "Vekâlet ücreti"),
        ("yapilmisBorcTahsilati", "Yapılmış borç tahsilatı"),
    )
    for key, label in extra_labels:
        val = _value(details.get(key))
        if val != "" and fold(label) not in seen:
            account.append((label, f"{val} ₺" if re.match(r"^-?\d+(\.\d+)?$", val) else val))
            seen.add(fold(label))
    return account


def case_information(record):
    """Kaynak bilgilerini alan bazında birleştirir; eksik yeni yanıt eski bilgiyi silmez."""
    if record is None or not isinstance(record.data, dict):
        return None
    data = record.data
    row = data.get("liste") if isinstance(data.get("liste"), dict) else {}
    details = merged_details(record)

    uyap_subject = uyap_subject_value(record)
    hearing_str = next_hearing_value(record)
    case_obj = getattr(record, "case", None)
    status_banner = (
        case_obj.uyap_status_banner
        if case_obj
        else (_value(row.get("dosyaDurum")) or _value(record.status))
    )

    closing_date_str = _date_value(
        details.get("dosyaKapanisTarihi") or details.get("kapanisTarihi")
    )
    if not closing_date_str and case_obj and case_obj.closed_on:
        closing_date_str = case_obj.closed_on.strftime("%d.%m.%Y")

    mediator_parts = [
        _value(details.get("arabulucu")),
        _value(details.get("arabulucuCepTel") or details.get("arabulucuTel")),
        _value(details.get("arabulucuEposta")),
    ]
    mediator_str = " · ".join(p for p in mediator_parts if p)

    definitions = [
        ("Durum / UYAP Aşama", (status_banner,)),
        ("Kurum", (row.get("birimAdi"), record.authority)),
        ("Dosya numarası", (row.get("dosyaNo"), record.number)),
        ("UYAP dosya türü", (row.get("dosyaTur"), row.get("dosyaTurKodAciklama"), record.category)),
        ("UYAP Dava Konusu", (uyap_subject,)),
        ("Dosya açılış tarihi", (details.get("dosyaAcilisTarihi"), row.get("dosyaAcilisTarihi"))),
        ("Dosya kapanış tarihi", (closing_date_str,)),
        ("Sıradaki duruşma tarihi", (hearing_str,)),
        ("Takibin türü", (details.get("takibinTuruAciklama"),)),
        ("Takibin yolu", (details.get("takibinYoluAciklama"),)),
        ("Takibin şekli", (details.get("takibinSekliAciklama"),)),
        ("Yürütmenin durdurulması", (details.get("yd"), details.get("ydli"))),
        ("Heyet durumu", (details.get("heyetli"),)),
        ("Karar numarası", (details.get("kararNo"),)),
        ("Karar tarihi", (details.get("kararTarihi"),)),
        ("Karar sonucu", (details.get("karar"), details.get("kararAciklama"))),
        ("Arabulucu", (mediator_str,)),
    ]
    fields = []
    date_labels = {
        "Dosya açılış tarihi",
        "Karar tarihi",
    }
    for label, candidates in definitions:
        convert = _date_value if label in date_labels else _value
        value = next((text for val in candidates if (text := convert(val))), "")
        if value:
            fields.append((label, value))

    return {
        "fields": fields,
        "account": account_items(record),
        "related_cases": extract_related_cases(record),
    }
