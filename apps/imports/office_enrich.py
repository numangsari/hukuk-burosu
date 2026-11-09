"""Eski ofis listelerindeki bilgileri dosyalara işler: karşı taraf, aşama, haciz ve notlar.

Yalnızca daha önce dosyaya bağlanmış `OfficeSourceRecord` satırları kullanılır. Her adım
tekrar çalıştırmada mükerrer kayıt üretmez."""

import re
from collections import Counter

from django.db import transaction

from apps.accounts.models import User
from apps.cases.models import CaseParty, CaseStatus, CaseType, Seizure
from apps.clients.models import Party
from apps.core.text import fold

from .models import OfficeSourceRecord

# İcra listesi KESİNLEŞME sütunu -> dosya aşaması
STAGE_BY_FINALIZATION = {
    "kesin": "finalized",
    "itiraz": "suspended",
    "tehiri icra": "suspended",
    "tebligat": "order_issued",
    "tekrar tebligat": "order_issued",
}
# İcra listesi True/False sütunu -> (haciz türü, "haciz var" durumu)
SEIZURE_COLUMNS = {
    "MAAŞ": ("salary", "salary_applied"),
    "BANKA": ("bank", "bank_seized"),
    "ARAÇ": ("vehicle", "vehicle_seized"),
    "TAŞINMAZ": ("property", "property_seized"),
    "İCRA DOSYASI": ("claim", "claim_exists"),
    "TAŞINIR": ("location", "location_seized"),
    "İİK 89": ("notice", "notice_requested"),
}
NOTE_LABELS = (
    "HACİZ NOTLARI",
    "TAHSİLAT NOTLARI",
    "KESİNLEŞME NOTLARI",
    "Not",
    "Ek bilgi",
    "Ek bilgi 2",
)
COMPANY_WORDS = (
    "sirketi",
    "limited",
    " ltd",
    " sti",
    "anonim",
    " a.s",
    "bakanligi",
    "mudurlugu",
    "valiligi",
    "belediyesi",
    "bankasi",
    "kurumu",
    "holding",
    "kooperatif",
)
_SPLIT = re.compile(r"\s+,\s+|\n|;")


def split_names(value):
    names = []
    for part in _SPLIT.split(value or ""):
        name = " ".join(part.split())
        if name and name not in {"-", "?", "—"} and len(name) <= 300:
            names.append(name)
    return names


def party_kind(name):
    folded = f" {fold(name)}"
    return "company" if any(word in folded for word in COMPANY_WORDS) else "person"


def party_role(case, opposite_is_left):
    if case.case_type == CaseType.ENFORCEMENT:
        return "creditor" if opposite_is_left else "debtor"
    if case.case_type == CaseType.CIVIL:
        return "plaintiff" if opposite_is_left else "defendant"
    return "opposing" if case.case_type == CaseType.MEDIATION else "other"


def _sides(record):
    values = record.values
    if "ALACAKLI" in values or "BORÇLU" in values:
        return split_names(values.get("ALACAKLI")), split_names(values.get("BORÇLU"))
    return split_names(values.get("Davacı")), split_names(values.get("Davalı"))


def _client_keys(case):
    keys = {fold(case.client.name)} if case.client_id else set()
    keys |= {fold(c.client.name) for c in case.co_client_links.all()}
    return keys


def _add_parties(case, record, user, counts):
    left, right = _sides(record)
    mine = _client_keys(case)
    on_left = any(fold(n) in mine for n in left)
    on_right = any(fold(n) in mine for n in right)
    if on_left == on_right:  # taraf belirsiz: dokunma
        return []
    opposite = right if on_left else left
    role = party_role(case, opposite_is_left=not on_left)
    known = {fold(link.party.name) for link in case.party_links.all()} | mine
    added = []
    for name in opposite:
        if fold(name) in known:
            continue
        party = Party.objects.create(kind=party_kind(name), name=name, created_by=user)
        CaseParty.objects.create(case=case, party=party, role=role)
        known.add(fold(name))
        added.append(party)
        counts["parties"] += 1
    return opposite


def _set_stage(case, record, counts):
    if case.case_type != CaseType.ENFORCEMENT or case.status != CaseStatus.OPEN or case.stage:
        return
    stage = STAGE_BY_FINALIZATION.get(fold(record.values.get("KESİNLEŞME", "")))
    if stage:
        case.stage = stage
        case.save(update_fields=["stage"], preserve_unknown_stage=True)
        counts["stages"] += 1


def _add_seizures(case, record, debtors, user, counts):
    if case.client_role != "creditor" or "ALACAKLI" not in record.values or user is None:
        return
    have = set(case.seizures.values_list("kind", flat=True))
    links = {fold(link.party.name): link.party for link in case.party_links.all()}
    for column, (kind, state) in SEIZURE_COLUMNS.items():
        if record.values.get(column) != "True" or kind in have:
            continue
        party = links.get(fold(debtors[0])) if len(debtors) == 1 else None
        Seizure.objects.create(
            case=case,
            kind=kind,
            state=state,
            debtor=", ".join(debtors)[:300] or "Belirtilmemiş",
            debtor_party=party,
            created_by=user,
        )
        counts["seizures"] += 1


def _add_notes(case, record, counts):
    lines = [
        f"Eski liste · {label}: {record.values[label]}"
        for label in NOTE_LABELS
        if len(re.sub(r"\W", "", str(record.values.get(label) or ""))) >= 2
    ]
    new = [line for line in lines if line not in (case.notes or "")]
    if new:
        case.notes = "\n".join(filter(None, [case.notes, *new]))
        case.save(update_fields=["notes"], preserve_unknown_stage=True)
        counts["notes"] += len(new)


@transaction.atomic
def enrich(apply=False):
    """Sayaçları döndürür; `apply=False` ise hiçbir değişiklik kalıcı olmaz."""
    counts = Counter()
    user = User.objects.filter(role="admin", is_active=True).order_by("pk").first()
    records = (
        OfficeSourceRecord.objects.filter(case__isnull=False)
        .select_related("case", "case__client")
        .order_by("pk")
    )
    cases = {}  # aynı dosyanın satırları tek nesneyi paylaşır (bayat kayıt üzerine yazılmasın)
    for record in records:
        case = cases.setdefault(record.case_id, record.case)
        counts["records"] += 1
        opposite = _add_parties(case, record, user, counts)
        _set_stage(case, record, counts)
        _add_seizures(case, record, opposite, user, counts)
        _add_notes(case, record, counts)
    if not apply:
        transaction.set_rollback(True)
    return counts
