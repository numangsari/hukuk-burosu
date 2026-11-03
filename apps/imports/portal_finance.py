"""UYAP tahsilat/reddiyat/harç kayıtlarını dosyanın muhasebesine aktarır.

Kurallar (kullanıcı kararları, 3 Kasım 2026):
- Yön tahsilat türüne değil, parayı kimin ödediğine/aldığına göre belirlenir.
- Ödeyen bizim tarafsa (müvekkil adı veya verisi çekilen avukat ödeyen metninde geçiyorsa;
  örn. "Davacı X 123 Vekili Y") tahsilat satırı MASRAF olur (gider/masraf avansı).
  Avansın harcandığını gösteren reddiyat (PTT, posta vb.) ve avansla karşılanan harç satırları
  ayrıca yazılmaz; aynı para iki kez sayılmaz.
- "Borç Tahsilatı"nda ödeyen borçlu ise ve müvekkilimiz alacaklıysa, müvekkile yapılan
  "Borç Reddiyatı"nın NET tutarı (ödenecek miktar) KARŞI TARAFTAN TAHSİLAT olur; tarih
  reddiyat tarihidir. Reddiyat henüz yoksa yazılmaz, sonraki taramada yazılır.
  Müvekkil borçluysa veya sıfatı belli değilse yazılmaz.
- Ödeyen müvekkilimiz değilse (başka kişi) satır atlanır.
- İcra harçları (başvurma, tahsil, cezaevi) yazılmaz. Diğer türlerde müvekkilin ödediği harç,
  müvekkilin avansını aşıyorsa yazılmaz, incelenmek üzere raporlanır.
- Kayıt müvekkile değil dosyaya işlenir. UYAP kaydı bağlı dosya yoksa numara/birim eşleşen
  büro dosyası kullanılır; ikisi de yoksa atlanır.
- Aynı satır tekrar yazılmaz (`LedgerEntry.portal_ref`).
"""

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounting.services import create_entry
from apps.core.text import fold

from .portal_matching import find_matching_case

DATE_FORMATS = (
    "%b %d, %Y %I:%M:%S %p",
    "%b %d, %Y",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
)
ZERO = Decimal("0.00")


def parse_date(value):
    text = str(value or "").strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_amount(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0 or amount >= Decimal("100000000000000"):
        return None
    return amount


def words(value):
    """Karşılaştırma için: harf büyük/küçük ve noktalama farkı yok, sözcükler boşlukla ayrılı."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", fold(str(value or ""))).split())


class Side:
    """Dosyada bizim tarafı (müvekkiller ve verisi çekilen avukatlar) tanıyan yardımcı."""

    def __init__(self, record, case):
        self.case = case
        self.clients = [(case.client, case.client_role)]
        for link in case.co_client_links.select_related("client"):
            self.clients.append((link.client, link.role))
        self.lawyers = [words(user.get_full_name()) for user in record.source_users.all()]
        self.lawyers = [name for name in self.lawyers if name]

    @staticmethod
    def contains(text, name):
        return bool(name) and f" {name} " in f" {text} "

    def client_in(self, text):
        """Metinde adı geçen müvekkil; yoksa None."""
        text = words(text)
        for client, _role in self.clients:
            if self.contains(text, words(client.name)):
                return client
        return None

    def is_ours(self, text):
        text = words(text)
        return bool(self.client_in(text)) or any(self.contains(text, name) for name in self.lawyers)

    def role_of(self, client):
        return next((role for item, role in self.clients if item.pk == client.pk), "")


def reference(record, kind, *parts):
    data = [record.fingerprint, kind, *[str(part or "") for part in parts]]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def rows(block, key):
    return [row for row in (block.get(key) or []) if isinstance(row, dict)]


def analyze(record, case):
    """Yazılacak hareketleri ve atlanan satırları (nedenleriyle) hesaplar; veritabanına yazmaz."""
    side = Side(record, case)
    entries, notes = [], []
    is_enforcement = case.case_type == "enforcement"
    for block in (b for b in (record.data or {}).get("tahsilatlar", []) if isinstance(b, dict)):
        own_advance = ZERO
        collections = rows(block, "tahsilatList")
        by_record = {str(row.get("kayitId")): row for row in collections if row.get("kayitId")}
        for row in collections:
            kind_text = fold(str(row.get("tahsilatTuru") or ""))
            payer = str(row.get("odeyenKisi") or "")
            amount = parse_amount(row.get("tahsilatTutari"))
            day = parse_date(row.get("tahsilatTarihi"))
            label = f"{row.get('tahsilatTuru') or 'Tahsilat'} · Makbuz {row.get('makbuzNo') or '-'}"
            if not amount or not day:
                notes.append(f"Tutar/tarih okunamadı: {label}")
            elif side.is_ours(payer):
                if "teminat" in kind_text:
                    notes.append(f"Teminat, masraf sayılmadı: {label} {amount}")
                    continue
                own_advance += amount
                entries.append(
                    {
                        "kind": EntryKind.EXPENSE,
                        "client": side.client_in(payer) or case.client,
                        "amount": amount,
                        "date": day,
                        "description": f"UYAP: {label}",
                        "ref": reference(
                            record, "gider", row.get("kayitId"), row.get("makbuzNo"), amount, day
                        ),
                    }
                )
            elif "borc tahsilat" not in kind_text:
                notes.append(f"Ödeyen müvekkil değil, atlandı: {label} · {payer} · {amount}")
        for row in rows(block, "reddiyatList"):
            reason = fold(str(row.get("reddiyatNedeni") or ""))
            recipient = str(row.get("odeyenKisi") or "")
            amount = parse_amount(row.get("odenecekMiktar") or row.get("miktar"))
            day = parse_date(row.get("reddiyatTarihi"))
            label = (
                f"{row.get('reddiyatNedeni') or 'Reddiyat'} · Makbuz {row.get('makbuzNo') or '-'}"
            )
            linked = by_record.get(str(row.get("kayitId"))) if row.get("kayitId") else None
            if "borc reddiyat" in reason:
                client = side.client_in(recipient)
                if not side.is_ours(recipient) or not amount or not day:
                    notes.append(f"Borç reddiyatı müvekkile değil/okunamadı: {label} · {recipient}")
                elif linked and "borc tahsilat" not in fold(str(linked.get("tahsilatTuru") or "")):
                    notes.append(f"Bağlı tahsilat borç tahsilatı değil: {label}")
                else:
                    owner = client or case.client
                    role = side.role_of(owner)
                    if role != "creditor":
                        why = "borçlu" if role == "debtor" else "sıfatı belirsiz"
                        notes.append(
                            f"Müvekkil {why}, borç reddiyatı yazılmadı: {label} · {amount}"
                        )
                        continue
                    gross = parse_amount(row.get("miktar"))
                    cut = (gross - amount) if gross and gross > amount else None
                    extra = f" (brüt {gross}, kesinti {cut})" if cut else ""
                    entries.append(
                        {
                            "kind": EntryKind.TRUST_IN,
                            "client": owner,
                            "amount": amount,
                            "date": day,
                            "description": f"UYAP: {label}{extra}",
                            "ref": reference(
                                record,
                                "tahsilat",
                                row.get("kayitId"),
                                row.get("makbuzNo"),
                                amount,
                                day,
                            ),
                        }
                    )
            elif side.is_ours(recipient):
                notes.append(
                    f"Müvekkile başka bir reddiyat (iade?), incelenmeli: {label} · {amount}"
                )
        own_fees = ZERO
        for row in rows(block, "harcList"):
            if side.is_ours(str(row.get("odeyenKisi") or "")):
                own_fees += parse_amount(row.get("miktar")) or ZERO
        if own_fees:
            if is_enforcement:
                notes.append(
                    f"İcra harçları yazılmadı (tahsilattan kesilir/alacak kalemi): {own_fees}"
                )
            elif own_fees > own_advance:
                notes.append(
                    f"Müvekkilin harcı {own_fees}, avansı {own_advance}: fark avansla karşılanmıyor, incelenmeli"
                )
    return entries, notes


def import_finance(record, dry_run=False):
    """Yazılanları ve atlananları döndürür: {'yazilan', 'atlanan', 'satirlar', 'notlar'}."""
    result = {"yazilan": 0, "atlanan": 0, "satirlar": [], "notlar": []}
    if not any(isinstance(b, dict) for b in (record.data or {}).get("tahsilatlar", [])):
        return result
    case = record.case or find_matching_case(record.authority, record.number)
    if case is None:
        result["notlar"].append("Büro dosyası bulunamadı, atlandı.")
        result["atlanan"] = 1
        return result
    entries, notes = analyze(record, case)
    result["notlar"] = notes
    result["atlanan"] = len(notes)
    for item in entries:
        exists = LedgerEntry.objects.filter(portal_ref=item["ref"]).exists()
        result["satirlar"].append(
            (
                "var" if exists else "yeni",
                item["kind"],
                item["amount"],
                item["date"],
                item["description"],
            )
        )
        if exists or dry_run:
            continue
        create_entry(
            LedgerEntry(
                client=item["client"],
                case=case,
                kind=item["kind"],
                amount=item["amount"],
                date=item["date"],
                description=item["description"][:300],
                portal_ref=item["ref"],
            )
        )
        result["yazilan"] += 1
    return result
