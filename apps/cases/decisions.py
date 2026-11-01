"""Safahat adımlarında seçilen karar türleri (dosya türüne göre).

Safahat yalnızca mahkeme/kurum aşamaları olan dosya türlerinde kullanılır.
Anahtarlar veritabanında saklanır; etiketler değişebilir, anahtarlar değişmemelidir.
"""

# Üst derece mahkemelerinin (istinaf, temyiz, Danıştay) ve yeniden yargılamanın ortak kararları.
_APPELLATE = [
    ("upheld", "Onama / Başvurunun esastan reddi"),
    ("upheld_corrected", "Düzelterek onama"),
    ("reversed", "Bozma"),
    ("set_aside_retrial", "Kaldırma ve yeniden yargılama"),
    ("set_aside_new_decision", "Kaldırma ve yeniden karar"),
    ("appeal_rejected_procedure", "Başvurunun usulden reddi"),
    ("rectification", "Karar düzeltme incelemesi"),
]

_COMMON_END = [
    ("merged", "Birleştirme"),
    ("no_jurisdiction", "Görevsizlik (dosya başka mahkemeye gönderildi)"),
    ("no_venue", "Yetkisizlik (dosya başka mahkemeye gönderildi)"),
    ("interim", "Ara karar"),
    ("other", "Diğer"),
]

DECISIONS = {
    "civil": [
        ("accepted", "Davanın tamamen kabulü"),
        ("partially_accepted", "Davanın kısmen kabulü"),
        ("rejected_merits", "Davanın esastan reddi"),
        ("rejected_procedure", "Davanın usulden reddi"),
        ("waiver", "Feragat nedeniyle sonuçlandı"),
        ("defendant_accept", "Davalının kabulü nedeniyle sonuçlandı"),
        ("settlement", "Sulh nedeniyle sonuçlandı"),
        ("moot", "Konusuz kaldı / Karar verilmesine yer olmadığı"),
        ("deemed_not_filed", "Davanın açılmamış sayılması"),
        *_APPELLATE,
        *_COMMON_END,
    ],
    "criminal": [
        ("acquittal", "Beraat"),
        ("conviction", "Mahkûmiyet"),
        ("no_penalty", "Ceza verilmesine yer olmadığı"),
        ("security_measure", "Güvenlik tedbirine hükmedilmesi"),
        ("hagb", "Hükmün açıklanmasının geri bırakılması"),
        ("dismissed", "Davanın düşmesi"),
        ("rejected", "Davanın reddi"),
        *_APPELLATE,
        *_COMMON_END,
    ],
    "administrative": [
        ("annulment", "İptal kararı"),
        ("partial_annulment", "Kısmen iptal kararı"),
        ("rejected_merits", "Davanın esastan reddi"),
        ("rejected_procedure", "Davanın usulden reddi"),
        ("full_remedy_accepted", "Tam yargı davasının kabulü"),
        ("full_remedy_partial", "Tam yargı davasının kısmen kabulü"),
        ("stay_of_execution", "Yürütmenin durdurulması"),
        ("stay_rejected", "Yürütmenin durdurulması isteminin reddi"),
        ("moot", "Konusuz kaldı / Karar verilmesine yer olmadığı"),
        *_APPELLATE,
        *_COMMON_END,
    ],
    "enforcement": [
        ("objection_cancelled", "İtirazın iptali"),
        ("objection_removed", "İtirazın kaldırılması"),
        ("objection_accepted", "İtirazın kabulü"),
        ("complaint_accepted", "Şikâyetin kabulü"),
        ("complaint_rejected", "Şikâyetin reddi"),
        ("enforcement_cancelled", "Takibin iptali"),
        ("claim_accepted", "İstihkak iddiasının kabulü"),
        ("claim_rejected", "İstihkak iddiasının reddi"),
        *_APPELLATE,
        *_COMMON_END,
    ],
    "investigation": [
        ("kyok", "Kovuşturmaya yer olmadığı kararı"),
        ("kyok_objection_accepted", "KYOK itirazının kabulü"),
        ("kyok_objection_rejected", "KYOK itirazının reddi"),
        ("indictment", "İddianame düzenlendi"),
        ("deferral", "Kamu davasının açılmasının ertelenmesi"),
        ("no_venue", "Yetkisizlik"),
        ("merged", "Birleştirme"),
        ("other", "Diğer"),
    ],
}

# Safahat sekmesi yalnızca bu dosya türlerinde görünür.
SAFAHAT_TYPES = set(DECISIONS)


def decisions_for(case_type):
    return DECISIONS.get(case_type, [])


def decision_label(case_type, key):
    return dict(decisions_for(case_type)).get(key, "")
