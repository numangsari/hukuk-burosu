"""Haciz türlerine göre kullanıcı tarafından belirlenen takip aşamaları."""

import datetime as dt

KINDS = [
    ("salary", "Maaş Haczi"),
    ("bank", "Banka Hesabı"),
    ("vehicle", "Araç Haczi"),
    ("property", "Tapu Haczi"),
    ("claim", "Alacaklı Olduğu İcra Dosyası Haczi"),
    ("location", "Mahal Haczi"),
    ("notice", "89/1-2-3 Haczi"),
]
STATES = {
    "salary": [
        ("salary_unemployed", "Çalışmıyor"),
        ("salary_employed", "Çalışıyor"),
        ("employer_letter", "İşverene Müzekkere Yazıldı"),
        ("salary_queued", "Maaş Haczi Sıraya Alındı"),
        ("salary_applied", "Maaş Haczi Uygulanıyor"),
        ("employer_no_reply", "İşveren Cevap Vermedi"),
    ],
    "bank": [
        ("bank_letter", "Bankaya Yazı Yazıldı"),
        ("bank_seized", "Haciz Konuldu"),
        ("bank_money_requested", "Dosyaya Para İstendi"),
        ("bank_no_money", "Bankada Para Yok"),
    ],
    "vehicle": [
        ("vehicle_none", "Araç Yok"),
        ("vehicle_seized", "Araç Var Haciz Konuldu"),
        ("capture_requested", "Yakalama İstendi"),
    ],
    "property": [
        ("property_none", "Tapu Yok"),
        ("property_seized", "Tapu Var Haciz Konuldu"),
        ("property_sale", "Tapu Var Satış İstendi"),
    ],
    "location": [
        ("location_seized", "Adrese gidildi ve haciz yapıldı"),
        ("location_failed", "Adrese gidildi haciz yapılamadı"),
    ],
    "notice": [
        ("notice_requested", "Talep Edildi"),
        ("notice_objected", "İtiraz Geldi"),
        ("notice_unobjected", "İtiraz Gelmedi"),
    ],
    "claim": [("claim_exists", "Var"), ("claim_none", "Yok")],
}
NOTICE_STAGES = [("89/1", "89/1"), ("89/2", "89/2"), ("89/3", "89/3")]
SEIZED_STATES = {
    "salary_queued",
    "salary_applied",
    "bank_seized",
    "bank_money_requested",
    "vehicle_seized",
    "capture_requested",
    "property_seized",
    "property_sale",
    "location_seized",
    "claim_exists",
}
RENEWAL_STATES = {
    "vehicle_seized",
    "capture_requested",
    "property_seized",
    "property_sale",
    "claim_exists",
}
DETAIL_FIELDS = {
    "salary": ["employer"],
    "bank": ["bank_name"],
    "vehicle": ["plate"],
    "property": ["property_info"],
    "location": ["address"],
    "notice": ["notice_stage", "recipient"],
    "claim": ["related_case_info"],
}


def suggested_renewal(seized_on):
    """Kullanıcının takip tercihi: bir yıl sonrasından 30 gün önce; hukuki süre hesabı değildir."""
    if not seized_on or seized_on.year >= 9999:
        return None
    try:
        anniversary = seized_on.replace(year=seized_on.year + 1)
    except ValueError:
        anniversary = seized_on.replace(year=seized_on.year + 1, day=28)
    return anniversary - dt.timedelta(days=30)
