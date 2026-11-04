"""Ofis listelerinin doğrulanabilen satırlarını ve inceleme gerekçelerini kaydeder."""

import hashlib
import io
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import load_workbook

from apps.cases.archive_locations import validate_archive_location
from apps.cases.models import Case, CaseStatus, CaseType
from apps.clients.models import Client
from apps.core.text import fold, tr_upper

from .models import OfficeSourceRecord
from .poa_review import get_teams

_NUMBER = re.compile(r"\s*(\d{4})\s*/\s*(\d+)\s*(?:E\.?|ESAS)?\s*", re.IGNORECASE)


def normalize_number(value):
    """`2026/151 E.`, `2026/151 E`, `2026/151 Esas` yazımlarını `2026/151` yapar; diğerine dokunmaz."""
    match = _NUMBER.fullmatch(value or "")
    return f"{match.group(1)}/{match.group(2)}" if match else value


def key(value):
    return tr_upper(unicodedata.normalize("NFC", " ".join(str(value or "").split())))


def text(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def amount(value):
    if value in (None, "", "-") or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            if "." in value and "," not in value and len(value.rsplit(".", 1)[-1]) > 2:
                raise ValueError
            value = (
                value.strip().replace(".", "").replace(",", ".") if "," in value else value.strip()
            )
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result >= Decimal("100000000000000"):
            raise ValueError
        if result != result.quantize(Decimal("0.01")):
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ValueError("Esas alacak tutarı okunamadı.") from None


@dataclass
class Row:
    source_hash: str
    source_name: str
    sheet: str
    number: int
    values: dict
    kind: str
    status: str
    folder: str
    archive_no: str
    authority: str
    official_no: str
    left: str
    right: str
    client_name: str = ""
    opened_on: date | None = None
    principal: object = None


def _files():
    base = Path(settings.BASE_DIR) / "veritabanı entegrasyon"
    return (
        Path(getattr(settings, "OFFICE_ARCHIVE_FILE", base / "DOSYA ARŞİV LİSTE.xlsx")),
        Path(getattr(settings, "OFFICE_ENFORCEMENT_FILE", base / "İCRA TAKİP LİSTESİ GÜNCEL.xlsx")),
    )


def read_sources():
    rows, hashes = [], {}
    for path in _files():
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        hashes[path] = digest
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        if path == _files()[0]:
            if set(workbook.sheetnames) != {"AÇIK", "KAPALI", "KAPALI1"}:
                raise ValueError("Arşiv listesinin sayfaları beklenen biçimde değil.")
            for sheet in workbook:
                folder = ""
                for number, record in enumerate(sheet.iter_rows(values_only=True), 1):
                    if sheet.title != "KAPALI1" and number == 1:
                        expected = [
                            "klasor no",
                            "dosya no",
                            "mahkeme",
                            "dosya/esas no",
                            "davaci",
                            "davali",
                        ]
                        if [fold(text(v)) for v in record[:6]] != expected:
                            raise ValueError("Arşiv listesinin başlıkları beklenen biçimde değil.")
                        continue
                    values = list(record) + [None] * 10
                    if sheet.title == "KAPALI1":
                        authority, official, left, right = map(text, values[:4])
                        place, file_no = "", ""
                        labels = ["Mahkeme", "Dosya numarası", "Davacı", "Davalı", "Not"]
                        snapshot = {
                            label: text(v)
                            for label, v in zip(labels, values[:5], strict=True)
                            if text(v)
                        }
                        snapshot.update(
                            {
                                f"Ek bilgi {i}": text(v)
                                for i, v in enumerate(values[5:], 1)
                                if text(v)
                            }
                        )
                    else:
                        if text(values[0]):
                            folder = text(values[0])
                        place = (
                            ("Açık " if sheet.title == "AÇIK" else "Kapalı ") + folder
                            if folder
                            else ""
                        )
                        file_no, authority, official, left, right = map(text, values[1:6])
                        labels = [
                            "Klasör no",
                            "Dosya no",
                            "Mahkeme",
                            "Dosya numarası",
                            "Davacı",
                            "Davalı",
                            "Not",
                            "Ek bilgi",
                            "Ek bilgi 2",
                        ]
                        snapshot = {
                            label: text(v)
                            for label, v in zip(labels, values[:9], strict=True)
                            if text(v)
                        }
                    relevant = values[:5] if sheet.title == "KAPALI1" else values[1:9]
                    if not any(text(value) for value in relevant):
                        continue
                    rows.append(
                        Row(
                            digest,
                            path.name,
                            sheet.title,
                            number,
                            snapshot,
                            "archive",
                            CaseStatus.OPEN if sheet.title == "AÇIK" else CaseStatus.CLOSED,
                            place,
                            file_no,
                            authority,
                            normalize_number(official),
                            left,
                            right,
                        )
                    )
        else:
            sheet = workbook.active
            header = next(sheet.iter_rows(values_only=True))
            if len(header) < 19 or fold(text(header[18])) != "esas alacak":
                raise ValueError("İcra listesinin başlıkları beklenen biçimde değil.")
            labels = [text(v) for v in header[:19]]
            for number, record in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                values = list(record) + [None] * 19
                authority, official, left, right, client = map(text, values[2:7])
                if not any((authority, official, left, right, client)):
                    continue
                snapshot = {
                    label: text(v)
                    for label, v in zip(labels[:18], values[:18], strict=True)
                    if text(v)
                }
                if text(values[18]):
                    snapshot[labels[18]] = text(values[18])
                opened = values[0].date() if isinstance(values[0], datetime) else values[0]
                if not isinstance(opened, date):
                    opened = None
                rows.append(
                    Row(
                        digest,
                        path.name,
                        sheet.title,
                        number,
                        snapshot,
                        "enforcement",
                        CaseStatus.OPEN,
                        "",
                        "",
                        authority,
                        normalize_number(official),
                        left,
                        right,
                        client,
                        opened,
                        values[18],
                    )
                )
        workbook.close()
    return hashes, rows


def archive_type(authority):
    name = fold(authority)
    if "icra" in name and not any(word in name for word in ("hukuk", "ceza", "mahkem")):
        return CaseType.ENFORCEMENT
    if any(word in name for word in ("arabuluculuk", "medıare", "mediare")) or name.startswith(
        "arb."
    ):
        return CaseType.MEDIATION
    if any(word in name for word in ("vergi mahkem", "idare mahkem")):
        return CaseType.ADMINISTRATIVE
    if any(word in name for word in ("ceza mahkem", "ascm", "acm")):
        return CaseType.CRIMINAL
    if name.endswith(" cbs") or "savcilig" in name:
        return CaseType.INVESTIGATION
    if any(
        word in name
        for word in (
            "hukuk mahkem",
            "aile mahkem",
            "is mahkem",
            "tuketici mahkem",
            "ticaret mahkem",
            "ashm",
            "shm",
        )
    ):
        return CaseType.CIVIL
    return None


def _client_index():
    result = defaultdict(list)
    for client in Client.objects.select_related("responsible_lawyer", "responsible_intern"):
        result[key(client.name)].append(client)
    return result


def _single(index, name):
    candidates = index.get(key(name), [])
    return candidates[0] if len(candidates) == 1 else None


def _role(row, client):
    name = key(client.name)
    left, right = name == key(row.left), name == key(row.right)
    if left == right:
        return ""
    if row.kind == "enforcement" or archive_type(row.authority) == CaseType.ENFORCEMENT:
        return "creditor" if left else "debtor"
    if archive_type(row.authority) == CaseType.CIVIL:
        return "plaintiff" if left else "defendant"
    return ""


def evaluate(row, index, location_counts, cases):
    if not row.authority or not row.official_no:
        return None, "Kurum veya dosya numarası eksik."
    if (
        len(row.authority) > 200
        or len(row.official_no) > 100
        or len(row.folder) > 50
        or len(row.archive_no) > 50
    ):
        return None, "Kaynak bilgisi ilgili alana sığmıyor."
    if row.kind == "archive":
        case_type = archive_type(row.authority)
        if not case_type:
            return None, "Dosya türü açıkça belirlenemedi."
        left, right = _single(index, row.left), _single(index, row.right)
        if bool(left) == bool(right):
            return None, "Müvekkil tarafı kesin olarak belirlenemedi."
        client = left or right
        if (
            row.folder
            and row.archive_no
            and location_counts[(key(row.folder), key(row.archive_no))] > 1
        ):
            return None, "Aynı arşiv yeri listede birden fazla kez geçiyor."
        principal = None
    else:
        case_type = CaseType.ENFORCEMENT
        client = _single(index, row.client_name)
        if not client:
            return None, "Müvekkil mevcut kayıtlarda tek bir kişiyle eşleşmedi."
        try:
            principal = amount(row.principal)
        except ValueError as exc:
            return None, str(exc)
    role = _role(row, client)
    if not role and (
        row.kind == "enforcement" or case_type in (CaseType.CIVIL, CaseType.ENFORCEMENT)
    ):
        return None, "Müvekkilin taraf sıfatı kesin olarak belirlenemedi."
    same_number = [
        c for c in cases if c.client_id == client.pk and key(c.official_no) == key(row.official_no)
    ]
    matches = [c for c in same_number if key(c.authority) == key(row.authority)]
    if len(matches) > 1 or (same_number and not matches):
        return None, "Benzer dosya bulundu; kurum veya kayıt eşleşmesi incelenmeli."
    existing = matches[0] if matches else None
    locations = [
        c
        for c in cases
        if row.folder
        and row.archive_no
        and key(c.archive_folder_no) == key(row.folder)
        and key(c.archive_no) == key(row.archive_no)
    ]
    if locations and (not existing or any(c.pk != existing.pk for c in locations)):
        return None, "Arşiv yeri başka bir dosyada kullanılıyor."
    if existing:
        if (
            existing.case_type != case_type
            or existing.status != row.status
            or existing.client_role != role
        ):
            return None, "Mevcut dosyanın türü, durumu veya tarafı kaynakla uyuşmuyor."
        if (
            row.folder
            and existing.archive_folder_no
            and (key(existing.archive_folder_no), key(existing.archive_no))
            != (key(row.folder), key(row.archive_no))
        ):
            return None, "Mevcut dosyanın arşiv yeri kaynakla uyuşmuyor."
        if row.kind == "enforcement" and existing.enforcement_amount not in (None, principal):
            return None, "Mevcut dosyanın esas alacak tutarı kaynakla uyuşmuyor."
    return (client, case_type, role, principal, existing), ""


def source_row(record):
    """Kayıtlı satırı kaynak dosyada bulur; dosya değişmişse None döner."""
    _, rows = read_sources()
    for row in rows:
        if (
            row.source_hash == record.source_sha256
            and row.sheet == record.sheet
            and row.number == record.row_number
        ):
            return row
    return None


def case_initial(record):
    """Yeni dosya formunu kaynak satırdan önceden doldurur; kesin olmayanı boş bırakır."""
    row = source_row(record)
    if row is None:
        return {}
    initial = {
        "authority": row.authority,
        "archive_folder_no": row.folder,
        "archive_no": row.archive_no,
    }
    case_type = CaseType.ENFORCEMENT if row.kind == "enforcement" else archive_type(row.authority)
    if case_type:
        initial["case_type"] = case_type
    match = re.fullmatch(r"(\d{4})/(\d+)", row.official_no.strip())
    if match:
        initial["official_year"], initial["official_sequence"] = map(int, match.groups())
    index = _client_index()
    if row.kind == "enforcement":
        client = _single(index, row.client_name)
    else:
        left, right = _single(index, row.left), _single(index, row.right)
        client = (left or right) if bool(left) != bool(right) else None
    if client:
        initial["client"] = client
        role = _role(row, client)
        if role:
            initial["client_role"] = role
    if row.opened_on:
        initial["opened_on"] = row.opened_on
    if row.kind == "enforcement":
        try:
            if (principal := amount(row.principal)) is not None:
                initial["enforcement_amount"] = principal
        except ValueError:
            pass
    return initial


def suggest_client(row, index):
    """Kaynak satırdan kesin müvekkil önerisi; belirsizse None."""
    if row.kind == "enforcement":
        return _single(index, row.client_name)
    left, right = _single(index, row.left), _single(index, row.right)
    return (left or right) if bool(left) != bool(right) else None


def create_case(record, row, client, case_type):
    """Kullanıcının seçtiği müvekkil ve türle dosya açar veya aynı dosyaya bağlar."""
    folder, archive_no = row.folder, row.archive_no
    if (
        len(row.authority) > 200
        or len(row.official_no) > 100
        or len(folder) > 50
        or len(archive_no) > 50
    ):
        raise ValidationError("Kaynak bilgisi ilgili alana sığmıyor.")
    same_number = [
        c
        for c in Case.objects.filter(client=client)
        if row.official_no and key(c.official_no) == key(row.official_no)
    ]
    matches = [c for c in same_number if key(c.authority) == key(row.authority)]
    if len(matches) == 1:
        return matches[0], "linked"
    if matches or same_number:
        raise ValidationError("Benzer dosya var; kurum veya kayıt eşleşmesi elle incelenmeli.")
    validate_archive_location(folder, archive_no, lock=True, import_legacy=True)
    if folder and archive_no:
        used = [
            c
            for c in Case.objects.filter(archive_folder_no__iexact=folder)
            if key(c.archive_no) == key(archive_no)
        ]
        if used:
            raise ValidationError("Arşiv yeri başka bir dosyada kullanılıyor.")
    document_type = case_type in (CaseType.OTHER, CaseType.CONSULTANCY)
    subject = (row.authority or row.official_no) if document_type else ""
    principal = None
    if row.kind == "enforcement" and case_type == CaseType.ENFORCEMENT:
        try:
            principal = amount(row.principal)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
    role = _role(row, client) if case_type in (CaseType.CIVIL, CaseType.ENFORCEMENT) else ""
    case = Case(
        client=client,
        case_type=case_type,
        client_role=role,
        archive_folder_no=folder,
        archive_no=archive_no,
        authority="" if document_type else row.authority,
        official_no="" if document_type else row.official_no,
        subject=subject,
        status=row.status,
        opened_on=row.opened_on,
        responsible_lawyer=client.responsible_lawyer,
        responsible_intern=client.responsible_intern,
        enforcement_amount=principal,
    )
    case.save(preserve_unknown_stage=True)
    return case, "created"


@transaction.atomic
def execute():
    """Tüm kaynaklar aynı kaldığında güvenli satırları kaydeder; diğerleri bekler."""
    hashes, rows = read_sources()
    teams = get_teams(lock=True)
    index = _client_index()
    cases = list(Case.objects.select_for_update().all())
    team_counts = [
        sum(
            case.responsible_lawyer_id == lawyer.pk and case.responsible_intern_id == intern.pk
            for case in cases
        )
        for lawyer, intern in teams
    ]
    locations = Counter(
        (key(r.folder), key(r.archive_no))
        for r in rows
        if r.kind == "archive" and r.folder and r.archive_no
    )
    counts = Counter()
    for row in rows:
        record = OfficeSourceRecord.objects.filter(
            source_sha256=row.source_hash, sheet=row.sheet, row_number=row.number
        ).first()
        if record and record.case_id:
            counts["previous"] += 1
            continue
        if record and record.skipped:
            counts["skipped"] += 1
            continue
        if record and not record.reason:
            record.reason = "Bağlı dosya silinmiş; satır yeniden incelenmeli."
            record.save(update_fields=["reason"])
            counts["pending"] += 1
            continue
        decision, reason = evaluate(row, index, locations, cases)
        case = None
        if decision:
            client, case_type, role, principal, case = decision
            if case is None:
                try:
                    validate_archive_location(
                        row.folder, row.archive_no, lock=True, import_legacy=True
                    )
                except ValidationError as exc:
                    decision, reason = None, exc.messages[0]
        if decision:
            if case is None:
                team_index = min(range(len(teams)), key=team_counts.__getitem__)
                lawyer, intern = teams[team_index]
                case = Case(
                    client=client,
                    case_type=case_type,
                    client_role=role,
                    archive_folder_no=row.folder,
                    archive_no=row.archive_no,
                    authority=row.authority,
                    official_no=row.official_no,
                    subject="",
                    status=row.status,
                    opened_on=row.opened_on,
                    responsible_lawyer=lawyer,
                    responsible_intern=intern,
                    enforcement_amount=principal,
                )
                case.save(preserve_unknown_stage=True)
                cases.append(case)
                team_counts[team_index] += 1
                counts["created"] += 1
            else:
                if (
                    row.kind == "enforcement"
                    and principal is not None
                    and case.enforcement_amount is None
                ):
                    case.enforcement_amount = principal
                    case.save(update_fields=["enforcement_amount"], preserve_unknown_stage=True)
                counts["linked"] += 1
        else:
            counts["pending"] += 1
        OfficeSourceRecord.objects.update_or_create(
            source_sha256=row.source_hash,
            sheet=row.sheet,
            row_number=row.number,
            defaults={
                "source_name": row.source_name,
                "values": row.values,
                "reason": reason,
                "case": case,
            },
        )
    if any(
        hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest in hashes.items()
    ):
        raise ValidationError("Kaynak dosyalar işlem sırasında değişti; aktarım geri alındı.")
    return counts
