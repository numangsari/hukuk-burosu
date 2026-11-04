"""UYAP ve UETS kayıtlarını büro dosyalarıyla akıllı eşleme yardımcıları."""

import re
import unicodedata
from datetime import timedelta

from django.utils import timezone

from apps.cases.models import Case


def normalize_text(text):
    """Metni Türkçe harf duyarsız, noktalama ve boşluklardan arındırarak normalize eder."""
    if not isinstance(text, str) or not text:
        return ""
    text = text.replace("I", "ı").replace("İ", "i").replace("ı", "i").lower()
    text = unicodedata.normalize("NFC", text)
    # Yaygın mahkeme kısaltmaları genişletilir
    text = re.sub(r"\bashm\b", "asliye hukuk mahkemesi", text)
    text = re.sub(r"\bacm\b", "asliye ceza mahkemesi", text)
    text = re.sub(r"\bashc\b", "asliye ceza mahkemesi", text)
    text = re.sub(r"\bshm\b", "sulh hukuk mahkemesi", text)
    text = re.sub(r"\bscm\b", "sulh ceza mahkemesi", text)
    text = re.sub(r"\bishm\b", "is mahkemesi", text)
    text = re.sub(r"\biş\b", "is", text)
    text = re.sub(r"[\s\.\-_/]+", " ", text).strip()
    return text


def extract_base_number(official_no):
    """2026/640 Esas, 2026/640 D.İş vb. formatlardan temel yıl/sayı (2026/640) kısmını ayıklar."""
    if not official_no:
        return ""
    match = re.search(r"(\d{4}/\d+)", str(official_no))
    return match.group(1) if match else str(official_no).strip()


def parse_notice_subject(subject):
    """
    Tebligat konusundan mahkeme ve dosya numarasını ayıklar.
    Örnek: 'Sakarya 5. Asliye Hukuk Mahkemesi [2022/40] [Sakarya 5. Asliye Hukuk Mahkemesi-5000875418332-0-2022/40]'
    Döndürür: (authority, number)
    """
    if not subject or not isinstance(subject, str):
        return None, None
    match = re.search(r"^(.*?)\s*\[(\d+/\d+)\]", subject.strip())
    if match:
        authority = match.group(1).strip()
        number = match.group(2).strip()
        return authority, number
    return None, None


def find_matching_case(authority, number, dosya_turu=None):
    """
    Verilen birim/mahkeme ve dosya numarasına (ve opsiyonel dosya türüne) göre
    sistemdeki tekil büro dosyasını bulmaya çalışır.
    """
    if not number:
        return None

    clean_num = extract_base_number(number)
    if not clean_num:
        return None

    norm_auth = normalize_text(authority)

    # Dosya numarası içeren adayları filtrele
    candidates = Case.objects.filter(official_no__icontains=clean_num).select_related("client")

    matches = []
    for case in candidates:
        case_base_num = extract_base_number(case.official_no)
        if case_base_num != clean_num:
            continue

        case_norm_auth = normalize_text(case.authority)

        # Mahkeme kontrolü (eğer mahkeme belirtilmişse)
        if norm_auth and case_norm_auth:
            is_mediation_match = case.case_type == "mediation" and (
                normalize_text(dosya_turu or "") == "arabuluculuk" or "arabuluc" in norm_auth
            )
            if (
                norm_auth == case_norm_auth
                or norm_auth in case_norm_auth
                or case_norm_auth in norm_auth
                or is_mediation_match
            ):
                matches.append(case)
        elif not norm_auth:
            # Mahkeme yoksa sadece tam numara eşleşenler
            matches.append(case)

    # Eğer tam 1 adet net eşleşme varsa döndür
    if len(matches) == 1:
        return matches[0]

    return None


def calculate_notice_due_date(delivered_at, days=None):
    """Tebligat teslim tarihine gün ekleyerek olası son tarihi hesaplar."""
    if days is None:
        from apps.office.models import OfficeSettings

        days = OfficeSettings.load().notice_default_due_days
    if not delivered_at:
        return timezone.localdate() + timedelta(days=days)
    base_date = delivered_at.date() if hasattr(delivered_at, "date") else delivered_at
    return base_date + timedelta(days=days)


def get_notice_urgency(due_date):
    """overdue / today / soon (≤3 gün) / normal — görevlerdeki renk sınıflarıyla tam uyumlu."""
    if not due_date:
        return "normal", ""
    today = timezone.localdate()
    days_left = (due_date - today).days
    if days_left < 0:
        return "overdue", f"{-days_left} gün gecikti"
    if days_left == 0:
        return "today", "Bugün"
    if days_left == 1:
        return "soon", "Yarın"
    if days_left <= 3:
        return "soon", f"{days_left} gün kaldı"
    return "normal", f"{days_left} gün kaldı"
