"""Dosya türüne göre aşamalar (açık dosya) ve kapanma seçenekleri (kapalı dosya).

Anahtarlar veritabanında saklanır; etiketler değişebilir, anahtarlar değişmemelidir.
Kapanma seçeneği bayrakları: "m" = tahsil/ödeme içerir (tutar ve tarih sorulur),
"n" = açıklama (not) zorunlu.
"""

from collections import namedtuple

Closing = namedtuple("Closing", "key label flags")

# Karar veren türlerde kapanışta karar tarihi ve karar numarası sorulur.
DECISION_TYPES = {"civil", "criminal", "administrative"}

_JUDICIAL_OPEN = [
    ("pending", "Derdest"),
    ("decided", "Karar verildi"),
    ("reasoned_awaited", "Gerekçeli karar bekleniyor"),
    ("reasoned_served", "Gerekçeli karar tebliğ edildi"),
    ("appeal", "İstinaf incelemesi"),
    ("cassation", "Temyiz incelemesi"),
]

OPEN_STAGES = {
    "sales_office": [],
    "civil": [
        *_JUDICIAL_OPEN,
        ("retrial", "Bozma / Kaldırma sonrası yeniden yargılama"),
        ("finalized", "Kesinleşti"),
    ],
    "criminal": [
        *_JUDICIAL_OPEN,
        ("retrial", "Bozma sonrası yeniden yargılama"),
        ("finalized", "Kesinleşti"),
    ],
    "administrative": [
        *_JUDICIAL_OPEN,
        ("retrial", "Bozma / Kaldırma sonrası inceleme"),
        ("finalized", "Kesinleşti"),
    ],
    "enforcement": [
        ("started", "Takip başlatıldı"),
        ("order_issued", "Ödeme / İcra emri düzenlendi"),
        ("order_served", "Ödeme / İcra emri tebliğ edildi"),
        ("suspended", "Takip durdu"),
        ("finalized", "Takip kesinleşti"),
        ("seizure", "Haciz aşaması"),
        ("sale", "Satış / İhale aşaması"),
        ("partial_collection", "Kısmi tahsilat"),
        ("dormant", "Dosya işlemsiz / Pasif"),
    ],
    "investigation": [
        ("complaint", "Suç duyurusu / Şikâyet yapıldı"),
        ("ongoing", "Soruşturma devam ediyor"),
        ("deferred", "Kamu davasının açılmasının ertelenmesi"),
        ("indictment", "İddianame düzenlendi"),
        ("kyok", "KYOK kararı verildi"),
        ("kyok_objection", "KYOK kararına itiraz incelemesi"),
    ],
    "consultancy": [
        ("draft", "Taslak"),
        ("negotiation", "Müzakere"),
        ("revision", "Revizyon"),
        ("client_approval", "Müvekkil onayı bekleniyor"),
        ("other_party_approval", "Karşı taraf onayı bekleniyor"),
        ("signature", "İmza bekleniyor"),
        ("notary", "Noter / Resmî işlem aşaması"),
        ("signed", "İmzalandı / Yürürlükte"),
    ],
    "mediation": [
        ("applied", "Başvuru yapıldı"),
        ("mediator_assigned", "Arabulucu atandı"),
        ("talks", "Görüşmeler devam ediyor"),
        ("agreement_draft", "Anlaşma metni hazırlanıyor"),
        ("final_minutes", "Son tutanak hazırlanıyor"),
        ("enforceability", "İcra edilebilirlik şerhi işlemleri"),
    ],
    "notice": [
        ("draft", "Taslak"),
        ("client_approval", "Müvekkil onayı bekleniyor"),
        ("notary", "Noter işlemleri"),
        ("sent", "İhtarname gönderildi"),
        ("service_awaited", "Tebligat bekleniyor"),
        ("served", "Tebliğ edildi / Cevap bekleniyor"),
        ("period_awaited", "Verilen sürenin dolması bekleniyor"),
        ("reply_review", "Cevap inceleniyor"),
        ("negotiation", "Müzakere devam ediyor"),
        ("reserve", "Yeniden tebligat işlemleri"),
    ],
    "other": [
        ("preparation", "Hazırlık"),
        ("info_awaited", "Belge / Bilgi bekleniyor"),
        ("applied", "Başvuru yapıldı"),
        ("in_progress", "İşlem devam ediyor"),
        ("reply_awaited", "Karşı taraf / Kurum cevabı bekleniyor"),
        ("approval_awaited", "Onay bekleniyor"),
        ("finishing", "Sonuçlandırma aşaması"),
    ],
}

CLOSING_REASONS = {
    "civil": [
        Closing("full_accept", "Davanın tamamen kabulü (kesinleşti)", "m"),
        Closing("partial_accept", "Davanın kısmen kabulü (kesinleşti)", "m"),
        Closing("rejected_merits", "Davanın esastan reddi (kesinleşti)", ""),
        Closing("rejected_procedure", "Davanın usulden reddi (kesinleşti)", ""),
        Closing("waiver", "Feragat nedeniyle sonuçlandı", ""),
        Closing("defendant_accept", "Davalının kabulü nedeniyle sonuçlandı", "m"),
        Closing("settlement", "Sulh nedeniyle sonuçlandı", "m"),
        Closing("moot", "Konusuz kaldı / Karar verilmesine yer olmadığı", ""),
        Closing("deemed_not_filed", "Davanın açılmamış sayılması", ""),
        Closing("merged", "Başka dosyayla birleştirildi", ""),
        Closing("no_jurisdiction", "Görevsizlik nedeniyle başka mahkemeye aktarıldı", ""),
        Closing("no_venue", "Yetkisizlik nedeniyle başka mahkemeye aktarıldı", ""),
        Closing("other", "Diğer", "n"),
    ],
    "criminal": [
        Closing("acquittal", "Beraat (kesinleşti)", ""),
        Closing("conviction", "Mahkûmiyet (kesinleşti)", ""),
        Closing("no_penalty", "Ceza verilmesine yer olmadığı (kesinleşti)", ""),
        Closing("security_measure", "Güvenlik tedbirine hükmedildi (kesinleşti)", ""),
        Closing("dismissed", "Davanın düşmesi (kesinleşti)", ""),
        Closing("rejected", "Davanın reddi (kesinleşti)", ""),
        Closing("hagb_expired", "HAGB denetim süresi sonunda düşme", ""),
        Closing("reconciliation", "Uzlaşma nedeniyle düşme", "m"),
        Closing("limitation", "Zamanaşımı nedeniyle düşme", ""),
        Closing("complaint_withdrawn", "Şikâyetten vazgeçme nedeniyle düşme", ""),
        Closing("prepayment", "Ön ödeme nedeniyle düşme", "m"),
        Closing("merged", "Başka dosyayla birleştirildi", ""),
        Closing("no_jurisdiction", "Görevsizlik nedeniyle başka mahkemeye aktarıldı", ""),
        Closing("no_venue", "Yetkisizlik nedeniyle başka mahkemeye aktarıldı", ""),
        Closing("other", "Diğer", "n"),
    ],
    "administrative": [
        Closing("annulment", "İptal kararı (kesinleşti)", ""),
        Closing("partial_annulment", "Kısmen iptal kararı (kesinleşti)", ""),
        Closing("rejected_merits", "Davanın esastan reddi (kesinleşti)", ""),
        Closing("rejected_procedure", "Davanın usulden reddi (kesinleşti)", ""),
        Closing("full_remedy_accept", "Tam yargı davasının kabulü (kesinleşti)", "m"),
        Closing("full_remedy_partial", "Tam yargı davasının kısmen kabulü (kesinleşti)", "m"),
        Closing("waiver", "Feragat nedeniyle sonuçlandı", ""),
        Closing("moot", "Konusuz kaldı / Karar verilmesine yer olmadığı", ""),
        Closing("deemed_not_filed", "Davanın açılmamış sayılması", ""),
        Closing("transferred", "Görevsizlik / Yetkisizlik nedeniyle aktarıldı", ""),
        Closing("merged", "Başka dosyayla birleştirildi", ""),
        Closing("other", "Diğer", "n"),
    ],
    "enforcement": [
        Closing("fully_collected", "Borcun tamamen tahsili / İnfazen kapandı", "m"),
        Closing("collected_outside", "Haricen tahsil nedeniyle kapandı", "m"),
        Closing("withdrawn", "Takipten vazgeçildi", ""),
        Closing("cancelled", "Takip iptal edildi", ""),
        Closing("cancellation_applied", "İcra emri / Takip iptali kararı uygulandı", ""),
        Closing("creditor_request", "Alacaklı talebiyle kapatıldı", ""),
        Closing("related_ended", "İlgili takip sona erdi", ""),
        Closing("transferred", "Başka dosyaya aktarıldı / Birleştirildi", ""),
        Closing("other", "Diğer", "n"),
    ],
    "investigation": [
        Closing("kyok_final", "KYOK kesinleşti", ""),
        Closing("indictment_accepted", "İddianame kabul edildi / Ceza davasına aktarıldı", ""),
        Closing("kyok_reconciliation", "Uzlaştırma sonucunda KYOK", "m"),
        Closing("kyok_prepayment", "Ön ödeme sonucunda KYOK", "m"),
        Closing(
            "kyok_after_deferral", "Kamu davasının açılmasının ertelenmesi sonrasında KYOK", ""
        ),
        Closing("fast_trial", "Seri muhakeme usulüyle sonuçlandı", ""),
        Closing("merged", "Başka soruşturmayla birleştirildi", ""),
        Closing("no_venue", "Yetkisizlik nedeniyle aktarıldı", ""),
        Closing("other", "Diğer", "n"),
    ],
    "consultancy": [
        Closing("signed", "İmzalandı / Hazırlama işi tamamlandı", ""),
        Closing("performed", "İfa edilerek sona erdi", ""),
        Closing("expired", "Süresi doldu", ""),
        Closing("mutual_end", "Tarafların anlaşmasıyla sona erdi", ""),
        Closing("terminated", "Feshedildi", ""),
        Closing("not_formed", "Sözleşme kurulamadı", ""),
        Closing("talks_failed", "Müzakereler sonuçsuz kaldı", ""),
        Closing("abandoned", "Hazırlanmaktan vazgeçildi", ""),
        Closing("other", "Diğer", "n"),
    ],
    "mediation": [
        Closing("full_agreement", "Tam anlaşma", "m"),
        Closing("partial_agreement", "Kısmi anlaşma", "m"),
        Closing("no_agreement", "Anlaşamama", ""),
        Closing("unsuitable", "Arabuluculuğa elverişli olmadığı tespit edildi", ""),
        Closing("other", "Diğer", "n"),
    ],
    "notice": [
        Closing("served", "Tebliğ edildi / İşlem tamamlandı", ""),
        Closing("replied", "Cevap alındı / İşlem tamamlandı", ""),
        Closing("period_expired", "Süre doldu / İşlem tamamlandı", ""),
        Closing("fulfilled", "Talep yerine getirildi", "m"),
        Closing("agreed", "Taraflar anlaştı", "m"),
        Closing("not_served", "Tebliğ edilemedi / İşlem sonlandırıldı", ""),
        Closing("abandoned", "İhtarname gönderilmesinden vazgeçildi", ""),
        Closing("escalated", "Dava / İcra sürecine aktarıldı", ""),
        Closing("other", "Diğer", "n"),
    ],
    "other": [
        Closing("completed", "Tamamlandı", ""),
        Closing("positive", "Olumlu sonuçlandı", ""),
        Closing("negative", "Olumsuz sonuçlandı", ""),
        Closing("agreed", "Anlaşmayla sonuçlandı", "m"),
        Closing("abandoned", "Vazgeçildi", ""),
        Closing("not_possible", "İşlem yapılamadı", ""),
        Closing("transferred", "Başka dosyaya aktarıldı", ""),
        Closing("other", "Diğer", "n"),
    ],
}


def open_stages(case_type):
    return OPEN_STAGES.get(case_type, OPEN_STAGES["other"])


def closing_reasons(case_type):
    return CLOSING_REASONS.get(case_type, CLOSING_REASONS["other"])


def default_stage(case_type):
    choices = open_stages(case_type)
    return choices[0][0] if choices else ""


def stage_label(case_type, key):
    return dict(open_stages(case_type)).get(key, "")


def closing_label(case_type, key):
    return {c.key: c.label for c in closing_reasons(case_type)}.get(key, "")


def closing_flags(case_type, key):
    return {c.key: c.flags for c in closing_reasons(case_type)}.get(key, "")
