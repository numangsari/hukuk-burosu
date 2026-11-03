"""Yalnızca ayrılmış deneme ortamındaki indirilmiş portal verilerini işler."""

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils.text import get_valid_filename

from apps.clients.models import Client
from apps.core.text import fold, tr_upper

from .models import PortalCapture, PortalCase, PortalNotice, PortalNoticeDocument
from .portal_case_sync import sync_portal_case
from .portal_finance import import_finance

SENSITIVE = re.compile(
    r"token|password|passwd|sifre|şifre|parola|secret|authorization|cookie|session|credential|otp|guvenlik.?kodu|güvenlik.?kodu|dogrulama|doğrulama|verification.?code|^pass$",
    re.I,
)
PRIVATE_PATH = re.compile(r"nats|login|logout|auth|token|session|sifre|password|giris", re.I)


def clean(value):
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if not SENSITIVE.search(str(key))}
    return value


def merge_portal_data(previous, current):
    """Eksik gelen portal yanıtı daha önce alınmış bilgileri silmez."""
    if isinstance(previous, dict) and isinstance(current, dict):
        merged = dict(previous)
        for key, value in current.items():
            merged[key] = merge_portal_data(merged[key], value) if key in merged else value
        return merged
    if isinstance(previous, list) and isinstance(current, list):
        return previous + [value for value in current if value not in previous]
    return previous if current in (None, "") else current


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def case_key(authority, number, case_kind):
    return digest([fold(" ".join(authority.split())), number.strip(), case_kind or ""])


def kind_for(row, category=""):
    categories = {
        "Ceza": "criminal",
        "CBS": "investigation",
        "Hukuk": "civil",
        "İcra": "enforcement",
        "İdari Yargı": "administrative",
        "Arabuluculuk": "mediation",
        "Satış Memurluğu": "sales_office",
    }
    text = fold(
        " ".join(
            [
                str(row.get(k) or "")
                for k in ("dosyaTur", "dosyaTurKodAciklama", "birimAdi", "yerelBirimAd")
            ]
            + [str(category or "")]
        )
    )
    if any(w in text for w in ("sorusturma", "cbs", "bassavci")):
        return "investigation"
    if category in categories:
        return categories[category]
    if "arabuluc" in text or category == "Arabuluculuk":
        return "mediation"
    if "ceza" in text or category == "Ceza":
        return "criminal"
    if "icra" in text or category == "İcra":
        return "enforcement"
    if "idari" in text or "idare" in text or category == "İdari Yargı":
        return "administrative"
    if "hukuk" in text or category == "Hukuk":
        return "civil"
    return None


def opening_date(row):
    value = row.get("dosyaAcilisTarihi")
    if isinstance(value, dict):
        value = value.get("date", {})
        try:
            return date(int(value["year"]), int(value["month"]), int(value["day"]))
        except (KeyError, TypeError, ValueError):
            pass
    return None


def closing_date(status):
    match = re.search(r"(\d{4}-\d{2}-\d{2})", status)
    if match:
        return date.fromisoformat(match.group(1))
    match = re.search(r"(\d{2}/\d{2}/\d{4})", status)
    if match:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date()
    return None


def decision_date(value):
    try:
        return datetime.strptime(str(value)[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def enforcement_amount(supplementary):
    for group in reversed(supplementary.get("hesaplar", [])):
        if not isinstance(group, list):
            continue
        for item in group:
            if (
                not isinstance(item, dict)
                or fold(str(item.get("textAlan") or "")) != "takipte kesinlesen miktar"
            ):
                continue
            try:
                amount = Decimal(str(item.get("degerAlan")))
                if (
                    amount.is_finite()
                    and amount.quantize(Decimal("0.01")) == amount
                    and abs(amount) < Decimal("100000000000000")
                ):
                    return amount
            except InvalidOperation:
                pass
    return None


def role_for(role):
    roles = {
        "davaci": "plaintiff",
        "davali": "defendant",
        "sanik": "accused",
        "musteki": "complainant",
        "magdur": "victim",
        "katilan": "participant",
        "suctan zarar goren": "injured",
        "musteki sanik": "complainant_accused",
        "alacakli": "creditor",
        "borclu": "debtor",
        "basvurucu": "applicant",
        "diger taraf": "opposing",
        "karsi taraf": "opposing",
    }
    return roles.get(fold(str(role or "")).replace("-", " ").strip(), "")


def represented(parties, hearing_parties, user):
    direct = []
    for party in parties:
        if not isinstance(party, dict):
            continue
        lawyers = str(party.get("vekil") or "").strip("[]").split(",")
        if any(fold(name.strip()) == fold(user.get_full_name()) for name in lawyers):
            direct.append(party)
    if parties:
        return direct
    # UYAP, duruşma taraflarını oturum sahibinin vekili olduğu kayıtla işaretler.
    return [
        {"adi": item.get("isim"), "rol": item.get("sifat"), "kisiKurum": "Kurum"}
        for item in hearing_parties
        if isinstance(item, dict)
        and item.get("isVekil") is True
        and any(
            word in fold(str(item.get("isim") or ""))
            for word in ("bakanligi", "mudurlugu", "valiligi")
        )
    ]


def client_for(party, user):
    name = str(party.get("adi") or "").strip()
    if not name:
        return None
    source_kind = fold(str(party.get("kisiKurum") or ""))
    if source_kind not in {"kurum", "kisi"}:
        return None
    kind = "company" if source_kind == "kurum" else "person"
    matches = list(Client.objects.filter(kind=kind, name=tr_upper(name).strip())[:2])
    if len(matches) > 1:
        return None
    if matches:
        return matches[0]
    if kind == "person":
        # Kaynaktaki tam ad aynı adlı kişiyi veya soyadın sınırını belirlemez.
        return None
    values = {
        "kind": kind,
        "responsible_lawyer": user,
        "responsible_intern": user,
        "created_by": user,
    }
    values["title" if kind == "company" else "first_name"] = name
    return Client.objects.create(**values)


def import_files(paths, user):
    items = []
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            values = json.load(stream)
        if isinstance(values, list):
            items.extend(values)
    return import_captures(items, user)


def check_import_access(user):
    if not settings.DEBUG:
        raise RuntimeError("Bu işlem yalnızca geliştirme modunda çalışır.")
    if not user.is_active or not user.is_office_admin:
        raise RuntimeError("Sorumlu kullanıcı etkin bir yönetici olmalı.")


@transaction.atomic
def import_notice_pdf(notice, source_part, content, user):
    if (
        not isinstance(content, bytes)
        or not content.startswith(b"%PDF-")
        or len(content) > 20_000_000
    ):
        raise ValueError("Belge geçerli bir PDF olmalı ve 20 MB sınırını aşmamalı.")
    return import_notice_document(notice, source_part, content, "belge.pdf", user)


@transaction.atomic
def import_notice_document(notice, source_part, content, filename, user):
    check_import_access(user)
    if not isinstance(source_part, str) or not source_part or len(source_part) > 256:
        raise ValueError("Belge kimliği geçersiz.")
    if not isinstance(content, bytes) or not content or len(content) > 20_000_000:
        raise ValueError("Belge boş olamaz ve 20 MB sınırını aşamaz.")
    suffix = PurePath(str(filename or "").replace("\\", "/")).suffix.lower()
    allowed = {
        ".pdf",
        ".udf",
        ".xml",
        ".zip",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".jpg",
        ".jpeg",
        ".png",
        ".txt",
        ".p7s",
    }
    if content.startswith(b"%PDF-"):
        suffix = ".pdf"
    elif suffix not in allowed or suffix == ".pdf":
        suffix = ".bin"
    try:
        name = get_valid_filename(PurePath(str(filename or "").replace("\\", "/")).stem)[:220]
    except SuspiciousFileOperation:
        name = ""
    name = name or "Tebligat_belgesi"
    content_hash = hashlib.sha256(content).hexdigest()
    document, created = PortalNoticeDocument.objects.get_or_create(
        notice=notice,
        source_part=source_part,
        content_hash=content_hash,
        defaults={"original_name": name + suffix},
    )
    if created:
        document.file.save(f"{content_hash}{suffix}", ContentFile(content), save=True)
    return document


@transaction.atomic
def import_captures(items, user, source_user=None):
    check_import_access(user)
    captures = {}
    for item in items:
        if not isinstance(item, dict) or item.get("source") not in ("UYAP", "UETS"):
            continue
        path_name = str(item.get("path") or "")
        if not path_name.startswith("/") or PRIVATE_PATH.search(path_name):
            continue
        data = clean(item.get("data"))
        key = digest([item["source"], path_name, data])
        captures[key] = {
            "source": item["source"],
            "path": path_name,
            "data": data,
            "captured_at": parse_datetime(str(item.get("capturedAt") or "")),
        }
    for key, item in captures.items():
        capture, _ = PortalCapture.objects.select_for_update().get_or_create(
            fingerprint=key, defaults={**item, "source_unknown": source_user is None}
        )
        if source_user:
            capture.source_users.add(source_user)

    cases = {}
    aliases = {}
    extra = defaultdict(lambda: defaultdict(list))
    hearings = []
    ordered = sorted(
        captures.values(), key=lambda item: item["captured_at"] or datetime.min.replace(tzinfo=UTC)
    )
    for item in ordered:
        data, path = item["data"], item["path"]
        if path == "/search_phrase_detayli.ajx":
            result = data.get("sonuc") if isinstance(data, dict) else data
            rows = (
                result[0]
                if isinstance(result, list) and result and isinstance(result[0], list)
                else []
            )
            for row in rows:
                if not isinstance(row, dict):
                    continue
                authority, number = (
                    str(row.get("birimAdi") or "").strip(),
                    str(row.get("dosyaNo") or "").strip(),
                )
                if not authority or not number:
                    continue
                category = data.get("kategori", "") if isinstance(data, dict) else ""
                key = case_key(authority, number, kind_for(row, category))
                cases[key] = {
                    "row": row,
                    "authority": authority,
                    "number": number,
                    "category": category,
                }
                if row.get("dosyaId"):
                    aliases[str(row["dosyaId"])] = key
        if path == "/avukat_durusma_sorgula_brd.ajx" and isinstance(data, list):
            hearings.extend(item for item in data if isinstance(item, dict))
        if item["source"] == "UETS" and path == "/v1/messages" and isinstance(data, list):
            for notice in data:
                if not isinstance(notice, dict):
                    continue
                ident = notice.get("id") or notice.get("messages_id")
                if not ident:
                    continue
                stamp = notice.get("inserttime")
                try:
                    delivered = datetime.fromtimestamp(int(stamp), tz=UTC)
                except (ValueError, TypeError, OverflowError, OSError):
                    delivered = None
                notice_record, _ = PortalNotice.objects.select_for_update().get_or_create(
                    fingerprint=digest(["UETS", str(ident)]),
                    defaults={
                        "sender": str(notice.get("sender_name") or "")[:300],
                        "subject": str(notice.get("subject") or ""),
                        "delivered_at": delivered,
                        "read": notice.get("status") == "read",
                        "data": notice,
                        "source_unknown": source_user is None,
                    },
                )
                if source_user:
                    notice_record.source_users.add(source_user)
                previous = dict(notice_record.data) if isinstance(notice_record.data, dict) else {}
                previous.update({key: value for key, value in notice.items() if key != "ayrinti"})
                notice_record.data = previous
                if notice.get("sender_name"):
                    notice_record.sender = str(notice["sender_name"])[:300]
                if notice.get("subject"):
                    notice_record.subject = str(notice["subject"])
                if delivered is not None:
                    notice_record.delivered_at = delivered
                if notice.get("status") in {"read", "unread"}:
                    notice_record.read = notice["status"] == "read"
                notice_record.save(
                    update_fields=["data", "read", "sender", "subject", "delivered_at"]
                )

    for hearing in hearings:
        authority, number = (
            str(hearing.get("yerelBirimAd") or "").strip(),
            str(hearing.get("dosyaNo") or "").strip(),
        )
        if not authority or not number:
            continue
        key = case_key(authority, number, kind_for(hearing))
        cases.setdefault(
            key, {"row": hearing, "authority": authority, "number": number, "category": ""}
        )
        if hearing.get("dosyaId"):
            aliases[str(hearing["dosyaId"])] = key
        if hearing not in extra[key]["durusmalar"]:
            extra[key]["durusmalar"].append(hearing)

    path_names = {
        "/dosyaAyrintiBilgileri_brd.ajx": "ayrintilar",
        "/dosya_taraf_bilgileri_brd.ajx": "taraf_listeleri",
        "/list_dosya_evraklar.ajx": "belge_listeleri",
        "/dosya_hesap_bilgileri.ajx": "hesaplar",
        "/dosya_tahsilat_reddiyat_bilgileri_brd.ajx": "tahsilatlar",
    }
    for item in ordered:
        path, data = item["path"], item["data"]
        if (
            path not in path_names
            or not isinstance(data, dict)
            or "sonuc" not in data
            or not data.get("dosyaId")
        ):
            continue
        key = aliases.get(str(data["dosyaId"]))
        value = data["sonuc"]
        if key and value not in extra[key][path_names[path]]:
            extra[key][path_names[path]].append(value)

    for key, info in cases.items():
        row, supplementary = info["row"], extra[key]
        status = str(row.get("dosyaDurum") or "")
        payload = {"liste": row, **dict(supplementary)}
        record, _ = PortalCase.objects.select_for_update().get_or_create(
            fingerprint=key,
            defaults={
                "source_unknown": source_user is None,
                "authority": info["authority"][:200],
                "number": info["number"][:100],
                "category": str(
                    row.get("dosyaTur") or row.get("dosyaTurKodAciklama") or info["category"]
                )[:40],
                "status": status[:200],
                "data": payload,
            },
        )
        if source_user:
            record.source_users.add(source_user)
        # Parçalı sorgular önceki ayrıntıları kaybettirmemelidir.
        if isinstance(record.data, dict):
            if isinstance(record.data.get("liste"), dict):
                payload["liste"] = merge_portal_data(record.data["liste"], payload["liste"])
            for field, previous in record.data.items():
                if field == "liste" or not isinstance(previous, list):
                    continue
                current = payload.setdefault(field, [])
                if isinstance(current, list):
                    payload[field] = previous + [
                        value for value in current if value not in previous
                    ]
        record.data = payload
        if status:
            record.status = status[:200]
        record.save(update_fields=["data", "status"])
        if record.case_id or source_user:
            sync_portal_case(
                record,
                default_user=source_user or user,
                create_missing=bool(source_user),
            )
        import_finance(record)
    return {
        "yanit": PortalCapture.objects.count(),
        "kaynak_dosya": PortalCase.objects.count(),
        "olusan_dosya": PortalCase.objects.filter(case__isnull=False).count(),
        "tebligat": PortalNotice.objects.count(),
    }
