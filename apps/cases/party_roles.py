"""Dosya türlerine göre taraf sıfatları."""

PARTY_ROLES = {
    "civil": [
        ("plaintiff", "Davacı"),
        ("defendant", "Davalı"),
        ("counter_plaintiff", "Karşı Davacı"),
        ("counter_defendant", "Karşı Davalı"),
        ("principal_intervener", "Asli Müdahil"),
        ("accessory_intervener", "Fer'î Müdahil"),
        ("notified", "İhbar Olunan"),
        ("interested", "İlgili Kişi"),
        ("third_party", "Üçüncü Kişi"),
    ],
    "criminal": [
        ("accused", "Sanık"),
        ("complainant", "Müşteki (Şikâyetçi)"),
        ("victim", "Mağdur"),
        ("participant", "Katılan"),
        ("injured", "Suçtan Zarar Gören"),
        ("financially_liable", "Malen Sorumlu"),
        ("complainant_accused", "Müşteki-Sanık"),
    ],
    "administrative": [
        ("plaintiff", "Davacı"),
        ("defendant_authority", "Davalı İdare"),
        ("plaintiff_intervener", "Davacı Yanında Müdahil"),
        ("defendant_intervener", "Davalı Yanında Müdahil"),
        ("interested", "İlgili Kişi"),
    ],
    "enforcement": [
        ("creditor", "Alacaklı"),
        ("debtor", "Borçlu"),
        ("third_party", "Üçüncü Kişi"),
        ("mortgagor", "İpotek Veren"),
        ("pledgor", "Rehin Veren"),
        ("surety", "Kefil"),
        ("avalist", "Avalist"),
        ("drawer", "Keşideci"),
        ("endorser", "Ciranta"),
        ("attachment_addressee", "Haciz İhbarnamesi Muhatabı"),
        ("ownership_claimant", "İstihkak İddia Eden"),
    ],
    "investigation": [
        ("suspect", "Şüpheli"),
        ("complainant", "Müşteki"),
        ("victim", "Mağdur"),
        ("complainant_suspect", "Müşteki-Şüpheli"),
        ("injured", "Suçtan Zarar Gören"),
        ("informant", "İhbar Eden"),
        ("interested", "İlgili Kişi"),
    ],
    "consultancy": [
        ("party_one", "Taraf 1"),
        ("party_two", "Taraf 2"),
        ("buyer", "Alıcı"),
        ("seller", "Satıcı"),
        ("tenant", "Kiracı"),
        ("landlord", "Kiraya Veren"),
        ("employee", "İşçi"),
        ("employer", "İşveren"),
        ("contractor", "Yüklenici"),
        ("principal", "İş Sahibi"),
        ("provider", "Hizmet Sağlayıcı"),
        ("recipient", "Hizmet Alan"),
        ("creditor", "Alacaklı"),
        ("debtor", "Borçlu"),
        ("surety", "Kefil"),
        ("guarantor", "Garantör"),
        ("assignor", "Devreden"),
        ("assignee", "Devralan"),
    ],
    "mediation": [
        ("applicant", "Başvuran"),
        ("opposing", "Karşı Taraf"),
        ("additional_party", "Diğer Taraf"),
    ],
    "notice": [
        ("notifier", "İhtar Eden"),
        ("notified_party", "İhtar Olunan"),
        ("informant", "İhbar Eden"),
        ("notified", "İhbar Olunan"),
        ("addressee", "Muhatap"),
        ("respondent", "Cevap Veren"),
    ],
    "other": [
        ("applicant", "Başvuran"),
        ("opposing", "Karşı Taraf"),
        ("interested", "İlgili Kişi"),
        ("addressee", "Muhatap"),
        ("third_party", "Üçüncü Kişi"),
        ("other", "Diğer"),
    ],
}

PARTY_ROLE_CHOICES = list(
    dict(pair for choices in PARTY_ROLES.values() for pair in choices).items()
)

# Dosya formunda taraflar iki karşıt yana ayrılır:
# (sol başlık, sol sıfatlar, sağ başlık, sağ sıfatlar).
# Listede olmayan türler (Sözleşme, Diğer) karışık tek listede gösterilir; iki yana
# girmeyen sıfatlar "Diğer ilgililer" bölümüne düşer.
PARTY_SIDES = {
    "civil": (
        "Davacı tarafı",
        ["plaintiff", "counter_defendant"],
        "Davalı tarafı",
        ["defendant", "counter_plaintiff"],
    ),
    "criminal": (
        "Şikâyetçi / mağdur tarafı",
        ["complainant", "victim", "participant", "injured"],
        "Sanık tarafı",
        ["accused", "financially_liable"],
    ),
    "administrative": (
        "Davacı tarafı",
        ["plaintiff", "plaintiff_intervener"],
        "Davalı idare tarafı",
        ["defendant_authority", "defendant_intervener"],
    ),
    "enforcement": (
        "Alacaklı tarafı",
        ["creditor"],
        "Borçlu tarafı",
        ["debtor", "mortgagor", "pledgor", "surety", "avalist", "drawer", "endorser"],
    ),
    "investigation": (
        "Şikâyetçi / mağdur tarafı",
        ["complainant", "victim", "injured", "informant"],
        "Şüpheli tarafı",
        ["suspect"],
    ),
    "mediation": ("Başvuran taraf", ["applicant"], "Karşı taraf", ["opposing"]),
    "notice": (
        "İhtar eden tarafı",
        ["notifier", "informant"],
        "İhtar olunan tarafı",
        ["notified_party", "notified", "addressee", "respondent"],
    ),
}


def party_lanes():
    """Tür başına form bölümleri: [{"label", "roles": [sıfat değerleri]}]."""
    lanes = {}
    for case_type, roles in PARTY_ROLES.items():
        values = [value for value, _ in roles]
        side = PARTY_SIDES.get(case_type)
        if not side:
            lanes[case_type] = [{"label": "Taraflar", "roles": values}]
            continue
        left_label, left, right_label, right = side
        result = [
            {"label": left_label, "roles": left},
            {"label": right_label, "roles": right},
        ]
        rest = [value for value in values if value not in left and value not in right]
        if rest:
            result.append({"label": "Diğer ilgililer", "roles": rest})
        lanes[case_type] = result
    return lanes
