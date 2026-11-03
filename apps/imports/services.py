"""Excel şablonundan toplu veri aktarımı: müvekkiller, dosyalar, açılış bakiyeleri.

Akış: şablon indirilir → doldurulur → yüklenir → önizleme (satır satır hata/uyarı) →
onaylanınca tek işlemde (transaction) aktarılır. Var olan kayıtlar atlanır, üzerine yazılmaz.
"""

import datetime as dt
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounting.services import create_entry
from apps.accounts.models import User
from apps.cases import stages
from apps.cases.models import Case, CaseStatus, CaseType
from apps.clients.models import Client, ClientContact, ClientIban, PersonKind
from apps.core.text import fold
from apps.core.validators import normalize_iban, validate_iban, validate_tckn, validate_vkn

CLIENT_COLS = [
    "Tür (Gerçek/Tüzel)", "Ad", "Soyad", "TC kimlik no", "Unvan", "Vergi kimlik no", "Vergi dairesi",
    "Telefon", "E-posta", "Adres", "IBAN", "Sorumlu avukat", "Sorumlu stajyer", "Notlar",
]  # fmt: skip
CASE_COLS = [
    "Müvekkil (ad/unvan veya TCKN/VKN)", "Dosya türü", "Arşiv no", "Resmi no", "Merci", "Konu", "Durum",
    "Aşama", "Değer", "Açılış tarihi", "Sorumlu avukat", "Sorumlu stajyer", "Notlar",
]  # fmt: skip
BALANCE_COLS = [
    "Müvekkil (ad/unvan veya TCKN/VKN)",
    "Tarih",
    "Ücret/masraf alacağı (₺)",
    "Emanetteki para (₺)",
    "Açıklama",
]

OPENING_NOTE = "Açılış bakiyesi (devir)"

SHEETS = {"Müvekkiller": CLIENT_COLS, "Dosyalar": CASE_COLS, "Açılış bakiyeleri": BALANCE_COLS}


def template_bytes() -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    examples = {
        "Müvekkiller": [
            ["Gerçek", "Ayşe", "ÖRNEK", "", "", "", "", "0555 000 00 00", "ayse@example.com", "Adres", "", "", "", "Örnek satır — silin"],
            ["Tüzel", "", "", "", "Örnek Ticaret A.Ş.", "", "Sakarya", "", "", "", "", "", "", "Örnek satır — silin"],
        ],
        "Dosyalar": [["Ayşe ÖRNEK", "Hukuk Davası", "2026/0100", "2026/123 E.", "Sakarya 1. Asliye Hukuk", "Alacak davası", "Derdest", "İlk derece", "150000", "15.01.2026", "", "", "Örnek satır — silin"]],
        "Açılış bakiyeleri": [["Ayşe ÖRNEK", "31.12.2025", "25000", "0", "Eski sistemden devir — örnek"]],
    }  # fmt: skip
    head_fill = PatternFill("solid", fgColor="0F1F38")
    for name, cols in SHEETS.items():
        ws = wb.create_sheet(name)
        ws.append(cols)
        for i, c in enumerate(cols, start=1):
            cell = ws.cell(1, i)
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), head_fill
            ws.column_dimensions[cell.column_letter].width = max(14, len(c) + 4)
        for row in examples[name]:
            ws.append(row)
        ws.freeze_panes = "A2"
    dv_kind = DataValidation(type="list", formula1='"Gerçek,Tüzel"', allow_blank=True)
    wb["Müvekkiller"].add_data_validation(dv_kind)
    dv_kind.add("A2:A2000")
    types = ",".join(label for _, label in CaseType.choices).replace("/", "-")
    if len(types) < 250:
        dv_type = DataValidation(type="list", formula1=f'"{types}"', allow_blank=True)
        wb["Dosyalar"].add_data_validation(dv_type)
        dv_type.add("B2:B2000")
    notes = wb.create_sheet("Açıklamalar", 0)
    for line in [
        "Özkurt Hukuk — veri aktarım şablonu",
        "",
        "• Her sayfada ilk satır başlıktır; değiştirmeyin. Örnek satırları silin.",
        "• Müvekkiller: Gerçek kişide Ad ve Soyad, tüzel kişide Unvan zorunludur.",
        "• Sorumlu avukat/stajyer boşsa aktarım ekranında seçilen varsayılan kişi atanır. Ad soyad sistemdeki kullanıcıyla aynı yazılmalıdır.",
        "• Dosyalar: Müvekkil sütununa müvekkilin adı/unvanı veya TCKN/VKN'si yazılır; müvekkil aynı dosyada veya sistemde olmalıdır.",
        f"• Dosya türleri: {', '.join(label for _, label in CaseType.choices)}",
        "• Durum: Açık veya Kapalı (boşsa Açık). Aşama sütunu: açık dosyada türün aşaması, kapalı dosyada kapanma nedeni (örn. Haricen tahsil nedeniyle kapandı); boşsa açıkta türün ilk aşaması atanır, kapalıda zorunludur.",
        "• Tarihler GG.AA.YYYY, tutarlar rakam olarak yazılır (ör. 15000,50).",
        "• Açılış bakiyeleri: eski sistemden devreden alacak 'Vekalet ücreti (devir)', emanetteki para 'Karşı taraftan tahsilat (devir)' olarak kaydedilir.",
        "• Sistemde zaten bulunan müvekkil (aynı TCKN/VKN veya ad) ve dosya (aynı arşiv no) atlanır; üzerine yazılmaz.",
    ]:
        notes.append([line])
    notes.column_dimensions["A"].width = 120
    notes["A1"].font = Font(bold=True, size=14)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@dataclass
class RowResult:
    sheet: str
    row: int
    label: str
    status: str  # create / skip / error
    messages: list[str] = field(default_factory=list)


@dataclass
class ImportPlan:
    rows: list[RowResult] = field(default_factory=list)
    clients: list = field(default_factory=list)  # (row_result, Client, contacts, iban)
    cases: list = field(default_factory=list)  # (row_result, Case, client_key)
    balances: list = field(default_factory=list)  # (row_result, client, date, fee, trust, desc)

    @property
    def errors(self):
        return [r for r in self.rows if r.status == "error"]

    def count(self, sheet, status):
        return sum(1 for r in self.rows if r.sheet == sheet and r.status == status)


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _date(v):
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    for f in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(_s(v), f).date()
        except ValueError:
            pass
    raise ValueError(f"Tarih anlaşılamadı: {v}")


def _money(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    text = _s(v).replace("₺", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as e:
        raise ValueError(f"Tutar anlaşılamadı: {v}") from e


def _choice(value, choices, label):
    if not _s(value):
        return ""
    key = fold(_s(value)).replace("-", "/")
    for code, text in choices:
        if fold(text).replace("-", "/") == key or code == _s(value):
            return code
    raise ValueError(f"{label} tanınmadı: {value}")


def _rows(ws, cols):
    header = [_s(c.value) for c in ws[1]][: len(cols)]
    if header != cols:
        raise ValueError(f"'{ws.title}' sayfasının başlıkları şablonla uyuşmuyor.")
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        values = list(row[: len(cols)]) + [None] * (len(cols) - len(row))
        if any(_s(v) for v in values):
            yield idx, dict(zip(cols, values, strict=False))


def build_plan(file_obj, default_lawyer, default_intern, file_hash: str = "") -> ImportPlan:
    try:
        wb = load_workbook(file_obj, data_only=True, read_only=True)
    except Exception as e:  # bozuk/şifreli dosya
        raise ValueError(
            "Excel dosyası okunamadı. Şablondan oluşturulmuş .xlsx dosyası yükleyin."
        ) from e
    users = {fold(str(u)): u for u in User.objects.filter(is_active=True)}
    plan = ImportPlan()
    if file_hash:
        from .models import ImportBatch

        if (
            batch := ImportBatch.objects.filter(file_sha256=file_hash)
            .select_related("created_by")
            .first()
        ):
            plan.rows.append(RowResult("Dosya", 0, "Bu Excel dosyası", "error", [
                f"Bu dosya {timezone.localtime(batch.created_at):%d.%m.%Y %H:%M} tarihinde {batch.created_by} tarafından zaten aktarıldı.",
            ]))  # fmt: skip
    # Kimlik numarası kesin eşleşmedir; ad yalnızca kimlik yoksa ve tek kişiye uyuyorsa kullanılır.
    by_id: dict[str, Client] = {}
    by_name: dict[str, list[Client]] = {}

    def remember(c, name):
        for k in (c.tckn, c.vkn):
            if k:
                by_id[k] = c
        by_name.setdefault(fold(name), []).append(c)

    for c in Client.objects.all():
        remember(c, c.name)

    def person(value, fallback, role_ok, what):
        if not _s(value):
            return fallback
        u = users.get(fold(_s(value)))
        if u is None:
            raise ValueError(f"{what} bulunamadı: {value}")
        if u.role not in role_ok:
            raise ValueError(f"{what} rolü uygun değil: {value}")
        return u

    def find_client(value):
        key = _s(value)
        if key in by_id:
            return by_id[key]
        matches = by_name.get(fold(key), [])
        if len(matches) > 1:
            raise ValueError(f"'{key}' adında birden fazla müvekkil var; bu sütuna TCKN/VKN yazın.")
        return matches[0] if matches else None

    if "Müvekkiller" in wb.sheetnames:
        for idx, r in _rows(wb["Müvekkiller"], CLIENT_COLS):
            res = RowResult("Müvekkiller", idx, "", "create")
            try:
                kind = _choice(
                    r["Tür (Gerçek/Tüzel)"] or "Gerçek",
                    [(PersonKind.PERSON, "Gerçek"), (PersonKind.COMPANY, "Tüzel")],
                    "Tür",
                )
                c = Client(
                    kind=kind, first_name=_s(r["Ad"]), last_name=_s(r["Soyad"]), tckn=_s(r["TC kimlik no"]),
                    title=_s(r["Unvan"]), vkn=_s(r["Vergi kimlik no"]), tax_office=_s(r["Vergi dairesi"]),
                    notes=_s(r["Notlar"]),
                    responsible_lawyer=person(r["Sorumlu avukat"], default_lawyer, ("admin", "senior", "lawyer"), "Sorumlu avukat"),
                    responsible_intern=person(r["Sorumlu stajyer"], default_intern, ("intern", "paralegal"), "Yardımcı sorumlu"),
                )  # fmt: skip
                c.clean()
                if c.tckn:
                    validate_tckn(c.tckn)
                if c.vkn:
                    validate_vkn(c.vkn)
                name = (
                    f"{c.first_name} {c.last_name}".strip()
                    if kind == PersonKind.PERSON
                    else c.title
                )
                res.label = name
                identity = c.tckn or c.vkn
                same_name = by_name.get(fold(name), [])
                if identity and identity in by_id:
                    res.status = "skip"
                    res.messages.append(f"Bu kimlik numarasıyla zaten kayıtlı: {by_id[identity]}")
                elif not identity and same_name:
                    raise ValueError(
                        f"Aynı adlı müvekkil zaten var ({same_name[0]}). Aynı kişiyse bu satırı silin; "
                        "farklı kişiyse TCKN/VKN yazın."
                    )
                else:
                    if same_name:
                        res.messages.append(
                            "Uyarı: aynı adlı başka bir müvekkil var (kimlik numarası farklı)."
                        )
                    iban = normalize_iban(_s(r["IBAN"]))
                    if iban:
                        validate_iban(iban)
                    contacts = [
                        (k, _s(r[col]))
                        for k, col in (
                            ("phone", "Telefon"),
                            ("email", "E-posta"),
                            ("address", "Adres"),
                        )
                        if _s(r[col])
                    ]
                    plan.clients.append((res, c, contacts, iban))
                    remember(c, name)
            except (ValueError, ValidationError) as e:
                res.status = "error"
                res.messages += e.messages if isinstance(e, ValidationError) else [str(e)]
            plan.rows.append(res)

    archive_seen = {
        number.casefold()
        for number in Case.objects.filter(archive_folder_no="").values_list("archive_no", flat=True)
    }
    if "Dosyalar" in wb.sheetnames:
        for idx, r in _rows(wb["Dosyalar"], CASE_COLS):
            res = RowResult("Dosyalar", idx, _s(r["Arşiv no"]) + " " + _s(r["Konu"]), "create")
            try:
                client = find_client(r["Müvekkil (ad/unvan veya TCKN/VKN)"])
                if client is None:
                    raise ValueError(
                        f"Müvekkil bulunamadı: {r['Müvekkil (ad/unvan veya TCKN/VKN)']}"
                    )
                archive = _s(r["Arşiv no"])
                if not archive or not _s(r["Konu"]):
                    raise ValueError("Arşiv no ve Konu zorunludur.")
                if archive.casefold() in archive_seen:
                    res.status = "skip"
                    res.messages.append("Bu arşiv numarası zaten kayıtlı.")
                else:
                    case_type = (
                        _choice(r["Dosya türü"], CaseType.choices, "Dosya türü") or CaseType.OTHER
                    )
                    status = _choice(r["Durum"], CaseStatus.choices, "Durum") or CaseStatus.OPEN
                    stage = reason = ""
                    if status == CaseStatus.CLOSED:
                        reasons = [(c.key, c.label) for c in stages.closing_reasons(case_type)]
                        reason = _choice(r["Aşama"], reasons, "Kapanma nedeni")
                        if not reason:
                            raise ValueError(
                                "Kapalı dosyada kapanma nedeni (Aşama sütunu) zorunludur."
                            )
                    else:
                        stage = _choice(r["Aşama"], stages.open_stages(case_type), "Aşama")
                    k = Case(
                        case_type=case_type, status=status, stage=stage, closing_reason=reason,
                        archive_no=archive, official_no=_s(r["Resmi no"]), authority=_s(r["Merci"]),
                        subject=_s(r["Konu"]), value=_money(r["Değer"]),
                        opened_on=_date(r["Açılış tarihi"]), notes=_s(r["Notlar"]),
                        responsible_lawyer=person(r["Sorumlu avukat"], client.responsible_lawyer, ("admin", "senior", "lawyer"), "Sorumlu avukat"),
                        responsible_intern=person(r["Sorumlu stajyer"], client.responsible_intern, ("intern", "paralegal"), "Yardımcı sorumlu"),
                    )  # fmt: skip
                    plan.cases.append((res, k, client))
                    archive_seen.add(archive.casefold())
            except (ValueError, ValidationError) as e:
                res.status = "error"
                res.messages += e.messages if isinstance(e, ValidationError) else [str(e)]
            plan.rows.append(res)

    if "Açılış bakiyeleri" in wb.sheetnames:
        for idx, r in _rows(wb["Açılış bakiyeleri"], BALANCE_COLS):
            res = RowResult(
                "Açılış bakiyeleri", idx, _s(r["Müvekkil (ad/unvan veya TCKN/VKN)"]), "create"
            )
            try:
                client = find_client(r["Müvekkil (ad/unvan veya TCKN/VKN)"])
                if client is None:
                    raise ValueError("Müvekkil bulunamadı.")
                fee, trust = (
                    _money(r["Ücret/masraf alacağı (₺)"]) or 0,
                    _money(r["Emanetteki para (₺)"]) or 0,
                )
                if fee < 0 or trust < 0:
                    raise ValueError("Tutarlar negatif olamaz.")
                if not fee and not trust:
                    raise ValueError("En az bir tutar girilmeli.")
                date, desc = _date(r["Tarih"]) or dt.date.today(), _s(r["Açıklama"])
                if client.pk:
                    same = LedgerEntry.objects.filter(
                        client=client,
                        date=date,
                        description=desc or OPENING_NOTE,
                        is_cancelled=False,
                    )
                    if fee and same.filter(kind=EntryKind.FEE, amount=fee).exists():
                        fee = 0
                        res.messages.append("Aynı ücret devri zaten kayıtlı; tekrar eklenmeyecek.")
                    if trust and same.filter(kind=EntryKind.TRUST_IN, amount=trust).exists():
                        trust = 0
                        res.messages.append("Aynı emanet devri zaten kayıtlı; tekrar eklenmeyecek.")
                if not fee and not trust:
                    res.status = "skip"
                else:
                    plan.balances.append((res, client, date, fee, trust, desc))
            except (ValueError, ValidationError) as e:
                res.status = "error"
                res.messages += e.messages if isinstance(e, ValidationError) else [str(e)]
            plan.rows.append(res)
    return plan


@transaction.atomic
def execute(plan: ImportPlan, user, file_hash: str = "", file_name: str = "") -> dict:
    if plan.errors:
        raise ValueError("Hatalı satırlar düzeltilmeden aktarım yapılamaz.")
    counts = {"clients": 0, "cases": 0, "balances": 0}
    for _res, c, contacts, iban in plan.clients:
        c.created_by = user
        c.save()
        for i, (kind, value) in enumerate(contacts):
            ClientContact.objects.create(client=c, kind=kind, value=value, is_primary=i == 0)
        if iban:
            ClientIban.objects.create(client=c, iban=iban, is_primary=True)
        counts["clients"] += 1
    for _res, k, client in plan.cases:
        k.client = Client.objects.get(pk=client.pk) if client.pk else client
        k.created_by = user
        k.save()
        counts["cases"] += 1
    for _res, client, date, fee, trust, desc in plan.balances:
        note = desc or OPENING_NOTE
        client_obj = Client.objects.get(pk=client.pk)
        for kind, amount in ((EntryKind.FEE, fee), (EntryKind.TRUST_IN, trust)):
            if amount:
                # Para hareketleri ortak muhasebe servisinden (müvekkil kilidi + bakiye kontrolü) geçer.
                create_entry(
                    LedgerEntry(
                        client=client_obj,
                        kind=kind,
                        amount=amount,
                        date=date,
                        description=note,
                        created_by=user,
                    )
                )
        counts["balances"] += 1
    if file_hash:
        from .models import ImportBatch

        ImportBatch.objects.create(
            file_sha256=file_hash, file_name=file_name[:200], created_by=user, counts=counts
        )
    return counts
