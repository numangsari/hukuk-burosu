"""UYAP kaynak kaydını (PortalCase) büro dosyası (Case), tarafları (CaseParty) ve safahatıyla (CaseFlow) eşitler."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.cases.models import (
    Case,
    CaseCoClient,
    CaseFlow,
    CaseParty,
    CaseStatus,
    Hearing,
    HearingKind,
    HearingStatus,
    NumberKind,
)
from apps.cases.party_roles import PARTY_ROLES
from apps.clients.models import Client, Party
from apps.core.text import fold, tr_upper

from .models import PortalCase
from .portal_display import (
    extract_related_cases,
    merged_details,
    next_hearing_value,
    uyap_stage_value,
    uyap_subject_value,
)
from .portal_matching import extract_base_number, find_matching_case, normalize_text


def kind_for_uyap(row, category=""):
    categories = {
        "Ceza": "criminal",
        "Hukuk": "civil",
        "İcra": "enforcement",
        "İdari Yargı": "administrative",
        "Arabuluculuk": "mediation",
        "Satış Memurluğu": "sales_office",
        "CBS": "investigation",
    }
    text = fold(
        " ".join(
            str(row.get(k) or "")
            for k in ("dosyaTur", "dosyaTurKodAciklama", "birimAdi", "yerelBirimAd")
        )
        + " "
        + str(category or "")
    )
    if "sorusturma" in text or "cbs" in text or "bassavci" in text or category == "CBS":
        return "investigation"
    if category in categories:
        return categories[category]
    if "satis memurlugu" in text:
        return "sales_office"
    if "arabuluc" in text:
        return "mediation"
    if "ceza" in text:
        return "criminal"
    if "icra" in text:
        return "enforcement"
    if "idari" in text or "idare" in text or "vergi" in text or "danistay" in text:
        return "administrative"
    if "hukuk" in text:
        return "civil"
    return "civil"


def number_kind_for(row, category=""):
    text = fold(
        " ".join(str(row.get(k) or "") for k in ("dosyaTur", "dosyaTurKodAciklama"))
        + " "
        + str(category or "")
    )
    if "talimat" in text:
        return NumberKind.COMMISSION
    if "degisik is" in text or "d.is" in text or "d. is" in text:
        return NumberKind.MISC
    return NumberKind.ESAS


def parse_uyap_date(value) -> date | None:
    if isinstance(value, dict):
        parts = value.get("date", value)
        if isinstance(parts, dict):
            try:
                return date(int(parts["year"]), int(parts["month"]), int(parts["day"]))
            except (KeyError, TypeError, ValueError):
                return None
        return None
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            pass
    match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    if match:
        try:
            return datetime.strptime(match.group(1), "%d/%m/%Y").date()
        except ValueError:
            pass
    match = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
    if match:
        try:
            return datetime.strptime(match.group(1), "%d.%m.%Y").date()
        except ValueError:
            pass
    return None


def parse_enforcement_amount(data: dict, details: dict) -> Decimal | None:
    for group in reversed(data.get("hesaplar") or []):
        if not isinstance(group, list):
            continue
        for item in group:
            if (
                not isinstance(item, dict)
                or fold(str(item.get("textAlan") or "")) != "takipte kesinlesen miktar"
            ):
                continue
            try:
                amount = Decimal(str(item.get("degerAlan"))).quantize(Decimal("0.01"))
                if amount.is_finite() and 0 <= amount < Decimal("100000000000000"):
                    return amount
            except (InvalidOperation, ValueError):
                pass
    raw = details.get("alacakKalemToplamTutar")
    if raw is not None and raw != "":
        try:
            amount = Decimal(str(raw)).quantize(Decimal("0.01"))
            if amount.is_finite() and 0 <= amount < Decimal("100000000000000"):
                return amount
        except (InvalidOperation, ValueError):
            pass
    return None


def map_enforcement_type(text: str) -> str:
    folded = fold(text)
    if "kambiyo" in folded:
        return "kambiyo"
    if "rehin" in folded or "ipotek" in folded:
        return "rehin"
    if "ilamli" in folded or ("ilam" in folded and "ilamsiz" not in folded):
        return "ilamli"
    if "ilamsiz" in folded or "abonelik" in folded:
        return "ilamsiz"
    return ""


def map_closing_reason(case_type: str, uyap_stage: str, details: dict) -> str:
    text = fold(
        f"{uyap_stage} {details.get('dosyaDurumu') or ''} {details.get('karar') or ''} {details.get('kararAciklama') or ''}"
    )
    if case_type == "enforcement":
        if "infaz" in text:
            return "fully_collected"
        if "haricen" in text:
            return "collected_outside"
        if "vazgec" in text or "feragat" in text:
            return "withdrawn"
        if "iptal" in text:
            return "cancelled"
        if "birles" in text or "aktar" in text:
            return "transferred"
        if "takipsiz" in text:
            return "other"
    elif case_type == "mediation":
        if "anlasamama" in text or "anlasmama" in text:
            return "no_agreement"
        if "kismi" in text and "anlasma" in text:
            return "partial_agreement"
        if "anlasma" in text:
            return "full_agreement"
    elif case_type in {"civil", "administrative"}:
        if "kismen kabul" in text:
            return "partial_accept" if case_type == "civil" else "partial_annulment"
        if "kabul" in text:
            return "full_accept" if case_type == "civil" else "annulment"
        if "feragat" in text:
            return "waiver"
        if "gorevsiz" in text:
            return "no_jurisdiction" if case_type == "civil" else "transferred"
        if "yetkisiz" in text:
            return "no_venue" if case_type == "civil" else "transferred"
        if "red" in text or "ret" in text:
            return "rejected_merits"
    elif case_type == "criminal":
        if "beraat" in text:
            return "acquittal"
        if "mahkumiyet" in text:
            return "conviction"
        if "dusme" in text:
            return "dismissed"
    return ""


def map_open_stage(case_type: str, uyap_stage: str) -> str:
    text = fold(uyap_stage)
    if case_type in {"civil", "criminal", "administrative"}:
        if "istinaf" in text and "dondu" in text:
            return "retrial"
        if "istinaf" in text or "bolge idare" in text or "bolge adliye" in text:
            return "appeal"
        if "yargitay" in text or "danistay" in text or "temyiz" in text:
            return "cassation"
        if "karara cikmis" in text or "karar verildi" in text:
            return "decided"
        if "kesinlesti" in text:
            return "finalized"
    return ""


def map_party_role(case_type: str, raw_role: str) -> str:
    text = fold(str(raw_role or "")).replace("-", " ").strip()
    valid = dict(PARTY_ROLES.get(case_type, []))
    direct = {
        "davaci": "plaintiff",
        "itiraz eden (davaci)": "plaintiff",
        "davali": "defendant_authority" if case_type == "administrative" else "defendant",
        "karsi taraf (davali)": (
            "defendant_authority" if case_type == "administrative" else "defendant"
        ),
        "itiraz eden (davali)": (
            "defendant_authority" if case_type == "administrative" else "defendant"
        ),
        "karsi davaci": "counter_plaintiff",
        "karsi davali": "counter_defendant",
        "asli mudahil": "principal_intervener",
        "feri mudahil": "accessory_intervener",
        "ihbar olunan": "notified",
        "ucuncu kisi": "third_party",
        "sanik": "accused",
        "supheli": "suspect",
        "musteki": "complainant",
        "magdur": "victim",
        "katilan": "participant",
        "suctan zarar goren": "injured",
        "musteki sanik": "complainant_accused",
        "katilan sanik": "complainant_accused",
        "ihbar eden": "informant",
        "alacakli": "creditor",
        "borclu": "debtor",
        "kefil": "surety",
        "ipotek veren": "mortgagor",
        "rehin veren": "pledgor",
        "basvurucu": "applicant",
        "basvuran": "applicant",
        "diger taraf": "opposing",
        "karsi taraf": "opposing",
    }
    mapped = direct.get(text, "")
    if mapped in valid:
        return mapped
    if "davaci" in text and "plaintiff" in valid:
        return "plaintiff"
    if "davali" in text:
        if "defendant_authority" in valid:
            return "defendant_authority"
        if "defendant" in valid:
            return "defendant"
    if "alacakli" in text and "creditor" in valid:
        return "creditor"
    if "borclu" in text and "debtor" in valid:
        return "debtor"
    if "sanik" in text and "accused" in valid:
        return "accused"
    if "katilan" in text and "participant" in valid:
        return "participant"
    if "musteki" in text and "complainant" in valid:
        return "complainant"
    if "magdur" in text and "victim" in valid:
        return "victim"
    if "basvur" in text and "applicant" in valid:
        return "applicant"
    if ("karsi" in text or "diger" in text) and "opposing" in valid:
        return "opposing"
    for fallback in ("interested", "other", "third_party"):
        if fallback in valid:
            return fallback
    return next(iter(valid), "other")


def extract_parties_from_record(record) -> list[dict]:
    """PortalCase içindeki taraf listesini standart sözlük listesi olarak döndürür."""
    if record is None or not isinstance(record.data, dict):
        return []
    data = record.data
    raw_list = []
    for item in reversed(data.get("taraf_listeleri") or []):
        if isinstance(item, list) and item:
            raw_list = item
            break
    if not raw_list:
        details = merged_details(record)
        if isinstance(details.get("dosyaTaraflari"), list):
            raw_list = details["dosyaTaraflari"]
    if not raw_list:
        for hearing in reversed(data.get("durusmalar") or []):
            if isinstance(hearing, dict) and isinstance(hearing.get("dosyaTaraflari"), list):
                raw_list = hearing["dosyaTaraflari"]
                break

    parties = []
    seen = set()
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        name = str(item.get("adi") or "").strip()
        if not name:
            first = str(item.get("isim") or "").strip()
            last = str(item.get("soyad") or "").strip()
            name = f"{first} {last}".strip()
        name = tr_upper(" ".join(name.split()))
        if not name:
            continue
        role_raw = str(item.get("rol") or item.get("sifat") or "").strip()
        lawyer = str(item.get("vekil") or "").strip().strip("[]").strip()
        kind_raw = fold(str(item.get("kisiKurum") or ""))
        if (
            kind_raw == "kurum"
            or item.get("isKamuKurumuMu") is True
            or any(
                w in fold(name)
                for w in (
                    "sirketi",
                    "bakanligi",
                    "mudurlugu",
                    "valiligi",
                    "belediyesi",
                    "bankasi",
                    "kurumu",
                )
            )
        ):
            kind = "company"
        else:
            kind = "person"
        key = (fold(name), fold(role_raw))
        if key in seen:
            continue
        seen.add(key)
        parties.append({"name": name, "raw_role": role_raw, "lawyer": lawyer, "kind": kind})
    return parties


def _default_assignees(record, default_user=None):
    from apps.clients.views import intern_by_lawyer
    from apps.office.models import OfficeSettings

    lawyer = record.source_users.filter(is_active=True).first() or default_user
    if not lawyer:
        lawyer = (
            User.objects.filter(
                is_active=True, role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER]
            )
            .order_by("pk")
            .first()
        )
    if not OfficeSettings.load().use_assistant_assignee:
        return lawyer, None
    intern_map = intern_by_lawyer()
    intern_id = intern_map.get(lawyer.pk) or intern_map.get(str(lawyer.pk)) if lawyer else None
    intern = User.objects.filter(pk=intern_id, is_active=True).first() if intern_id else None
    if not intern:
        intern = (
            User.objects.filter(is_active=True, role__in=[User.Role.INTERN, User.Role.PARALEGAL])
            .order_by("pk")
            .first()
            or lawyer
        )
    return lawyer, intern


def _match_office_clients(parties: list[dict], record) -> list[tuple[Client, str]]:
    """Taraf listesinde mevcut ofis müvekkilleriyle eşleşenleri (vekil kontrolüyle) bulur."""
    lawyer_names = {fold(u.get_full_name()) for u in record.source_users.all() if u.get_full_name()}
    represented_matches = []
    name_matches = []
    for party in parties:
        candidates = list(Client.objects.filter(name=party["name"])[:2])
        if len(candidates) != 1:
            continue
        client = candidates[0]
        party_lawyers = [fold(x.strip()) for x in party["lawyer"].split(",") if x.strip()]
        if lawyer_names and any(l_name in party_lawyers for l_name in lawyer_names):
            represented_matches.append((client, party["raw_role"]))
        else:
            name_matches.append((client, party["raw_role"]))
    return represented_matches or name_matches


def link_cases_flow(case_a: Case, case_b: Case, note: str = ""):
    """İki dosyayı ortak safahat (CaseFlow) grubunda birleştirir (müvekkil eksik olsa da çalışır)."""
    if case_a.pk == case_b.pk:
        return
    flow = case_a.flow or case_b.flow
    if flow is None:
        flow = CaseFlow.objects.create()
    elif case_a.flow_id and case_b.flow_id and case_a.flow_id != case_b.flow_id:
        old_flow_id = case_b.flow_id
        max_pos = Case.objects.filter(flow=flow).count()
        for idx, member in enumerate(
            Case.objects.filter(flow_id=old_flow_id).order_by("flow_position", "pk"),
            start=max_pos + 1,
        ):
            member.flow = flow
            member.flow_position = idx
            member.save(update_fields=["flow", "flow_position"])
        CaseFlow.objects.filter(pk=old_flow_id).delete()
        return

    for target in (case_a, case_b):
        if target.flow_id != flow.pk:
            pos = Case.objects.filter(flow=flow).count() + 1
            target.flow = flow
            target.flow_position = pos
            if note and not target.flow_note and target.pk == case_b.pk:
                target.flow_note = note
            target.save(update_fields=["flow", "flow_position", "flow_note"])


@transaction.atomic
def sync_portal_case(
    record: PortalCase,
    default_user: User | None = None,
    create_missing: bool = False,
    sync_related: bool = True,
) -> Case | None:
    """PortalCase verilerini büro dosyasına, taraflara ve safahata aktarır."""
    if not isinstance(record.data, dict):
        return record.case
    data = record.data
    row = data.get("liste") if isinstance(data.get("liste"), dict) else {}
    details = merged_details(record)

    authority = tr_upper(str(row.get("birimAdi") or record.authority or "")).strip()[:200]
    raw_number = str(row.get("dosyaNo") or record.number or "").strip()
    clean_no = extract_base_number(raw_number) or raw_number[:100]
    case_type = kind_for_uyap(row, record.category)
    no_kind = number_kind_for(row, record.category)
    parties = extract_parties_from_record(record)

    case = record.case
    if case is None:
        matched = find_matching_case(authority, clean_no, record.category)
        if matched and not PortalCase.objects.filter(case=matched).exclude(pk=record.pk).exists():
            case = matched
            record.case = case
            record.save(update_fields=["case"])

    if case is None and create_missing:
        lawyer, intern = _default_assignees(record, default_user)
        if not lawyer:
            return None
        matched_clients = _match_office_clients(parties, record)
        primary_client = matched_clients[0][0] if matched_clients else None
        primary_role = map_party_role(case_type, matched_clients[0][1]) if matched_clients else ""
        if primary_client:
            lawyer = primary_client.responsible_lawyer or lawyer
            intern = primary_client.responsible_intern or intern

        case = Case(
            client=primary_client,
            client_role=primary_role,
            case_type=case_type,
            authority=authority,
            official_no=clean_no,
            official_no_kind=no_kind,
            subject="",
            archive_folder_no="",
            archive_no="",
            responsible_lawyer=lawyer,
            responsible_intern=intern,
            created_by=default_user or lawyer,
        )
        case.save()
        for extra_client, extra_raw_role in matched_clients[1:]:
            if extra_client.pk != primary_client.pk:
                CaseCoClient.objects.get_or_create(
                    case=case,
                    client=extra_client,
                    defaults={"role": map_party_role(case_type, extra_raw_role)},
                )
        record.case = case
        record.save(update_fields=["case"])

    if case is None:
        return None

    case = Case.objects.select_for_update().get(pk=case.pk)

    # UYAP alanlarını büro dosyasına eşitle
    if authority and not (
        case.case_type == "mediation"
        and case.authority
        and fold(authority) == "arabuluculuk daire baskanligi"
    ):
        case.authority = authority
    if clean_no:
        case.official_no = clean_no
    case.official_no_kind = no_kind
    if case_type:
        case.case_type = case_type

    opened = parse_uyap_date(details.get("dosyaAcilisTarihi") or row.get("dosyaAcilisTarihi"))
    if opened:
        case.opened_on = opened

    case.uyap_stage = uyap_stage_value(record)[:200]
    case.uyap_subject = uyap_subject_value(record)[:500]
    case.next_hearing_at = next_hearing_value(record)[:100]

    raw_status = str(row.get("dosyaDurum") or record.status or "")
    detail_status = str(details.get("dosyaDurumu") or "")
    is_closed = (
        row.get("dosyaDurumKod") == 1
        or fold(raw_status).startswith("kapali")
        or fold(detail_status).startswith("kapali")
    )
    if is_closed:
        case.status = CaseStatus.CLOSED
        case.stage = ""
        closed_dt = (
            parse_uyap_date(raw_status)
            or parse_uyap_date(details.get("dosyaKapanisTarihi"))
            or parse_uyap_date(details.get("kapanisTarihi"))
            or parse_uyap_date(details.get("kararTarihi"))
        )
        if closed_dt:
            case.closed_on = closed_dt
        mapped_reason = map_closing_reason(case.case_type, case.uyap_stage, details)
        if mapped_reason and not case.closing_reason:
            case.closing_reason = mapped_reason
    elif raw_status or detail_status:
        case.status = CaseStatus.OPEN
        mapped_stage = map_open_stage(case.case_type, case.uyap_stage)
        if mapped_stage:
            case.stage = mapped_stage

    if details.get("kararNo"):
        case.decision_no = str(details["kararNo"]).replace(" ", "")[:100]
    dec_dt = parse_uyap_date(details.get("kararTarihi"))
    if dec_dt:
        case.decision_date = dec_dt

    if case.case_type == "enforcement":
        enf_type = map_enforcement_type(str(details.get("takibinTuruAciklama") or ""))
        if enf_type:
            case.enforcement_type = enf_type
        enf_amount = parse_enforcement_amount(data, details)
        if enf_amount is not None:
            case.enforcement_amount = enf_amount

    if case.case_type == "mediation" and details.get("arabulucu"):
        case.mediator = str(details["arabulucu"]).strip()[:200]

    # Müvekkil henüz atanmamışsa ve taraf listesinde mevcut müvekkille eşleşme varsa bağla
    if not case.client_id and parties:
        matched_clients = _match_office_clients(parties, record)
        if matched_clients:
            case.client = matched_clients[0][0]
            case.client_role = map_party_role(case.case_type, matched_clients[0][1])

    # Tarafları (CaseParty ve müvekkil sıfatlarını) senkronize et
    client_folds = {}
    if case.client_id:
        client_folds[fold(case.client.name)] = ("primary", case.client)
    for co_link in case.co_client_links.select_related("client"):
        client_folds[fold(co_link.client.name)] = ("co", co_link)

    for party_info in parties:
        role_code = map_party_role(case.case_type, party_info["raw_role"])
        p_fold = fold(party_info["name"])
        if p_fold in client_folds:
            kind_tag, obj = client_folds[p_fold]
            if kind_tag == "primary":
                case.client_role = role_code
            else:
                if obj.role != role_code:
                    obj.role = role_code
                    obj.save(update_fields=["role"])
            continue

        existing_link = (
            case.party_links.select_related("party").filter(party__name=party_info["name"]).first()
        )
        if existing_link:
            updates = []
            if existing_link.role != role_code:
                existing_link.role = role_code
                updates.append("role")
            if not existing_link.from_uyap:
                existing_link.from_uyap = True
                updates.append("from_uyap")
            if updates:
                existing_link.save(update_fields=updates)
            if party_info["lawyer"] and existing_link.party.lawyer != party_info["lawyer"][:200]:
                existing_link.party.lawyer = party_info["lawyer"][:200]
                existing_link.party.save(update_fields=["lawyer"])
        else:
            party_obj = Party.objects.create(
                kind=party_info["kind"],
                name=party_info["name"],
                lawyer=party_info["lawyer"][:200],
                created_by=case.created_by or default_user,
            )
            CaseParty.objects.create(
                case=case,
                party=party_obj,
                role=role_code,
                from_uyap=True,
            )

    case.save(preserve_unknown_stage=True)
    sync_record_hearings(case, record, default_user=default_user)

    if sync_related:
        for rel in extract_related_cases(record):
            rel_case = find_matching_case(rel["authority"], rel["number"])
            if rel_case is None:
                rel_norm_auth = normalize_text(rel["authority"])
                rel_clean_no = extract_base_number(rel["number"])
                for other_pc in PortalCase.objects.filter(number__icontains=rel_clean_no):
                    if (
                        extract_base_number(other_pc.number) == rel_clean_no
                        and normalize_text(other_pc.authority) == rel_norm_auth
                    ):
                        rel_case = sync_portal_case(
                            other_pc,
                            default_user=default_user,
                            create_missing=create_missing,
                            sync_related=False,
                        )
                        break
            if rel_case:
                link_cases_flow(case, rel_case, f"UYAP {rel['relation']}")

    return case


def missing_related_cases_for_view(case: Case) -> list[dict]:
    """Safahat sekmesinde henüz sistemde dosyası olmayan UYAP ilgili dosyalarını döndürür."""
    portal = getattr(case, "portalcase", None)
    if not portal:
        return []
    flow_cases = list(Case.objects.filter(flow_id=case.flow_id)) if case.flow_id else [case]
    missing = []
    for rel in extract_related_cases(portal):
        rel_norm_auth = normalize_text(rel["authority"])
        rel_clean_no = extract_base_number(rel["number"])
        already_in_flow = any(
            extract_base_number(m.official_no) == rel_clean_no
            and normalize_text(m.authority) == rel_norm_auth
            for m in flow_cases
        )
        if already_in_flow:
            continue
        existing = find_matching_case(rel["authority"], rel["number"])
        year_part, seq_part = "", ""
        if "/" in rel_clean_no:
            year_part, seq_part = rel_clean_no.split("/", 1)
        missing.append(
            {
                **rel,
                "existing_case": existing,
                "year": year_part,
                "sequence": seq_part,
            }
        )
    return missing


def map_hearing_kind(raw_kind: str) -> str:
    f = fold(str(raw_kind or ""))
    if "kesif" in f:
        return HearingKind.DISCOVERY
    if "on inceleme" in f:
        return HearingKind.PRELIMINARY
    if "bilirkisi" in f:
        return HearingKind.EXPERT
    if "arabuluculuk" in f:
        return HearingKind.MEDIATION
    if "durusma" in f:
        return HearingKind.HEARING
    return HearingKind.OTHER


def map_hearing_status(result_desc: str) -> str:
    f = fold(str(result_desc or ""))
    if "ertelendi" in f or "tarih verildi" in f:
        return HearingStatus.POSTPONED
    if "yapildi" in f or "karara cikti" in f or "hukum" in f:
        return HearingStatus.HELD
    if "iptal" in f:
        return HearingStatus.CANCELLED
    return HearingStatus.PLANNED


def parse_hearing_datetime(raw_str: str) -> datetime | None:
    if not raw_str:
        return None
    s = str(raw_str).strip()
    if "." in s:
        s = s.split(".")[0]
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%Y-%m-%d",
        "%d.%m.%Y",
    ):
        try:
            dt_obj = datetime.strptime(s, fmt)
            if timezone.is_naive(dt_obj):
                dt_obj = timezone.make_aware(dt_obj)
            return dt_obj
        except ValueError:
            continue
    return None


def sync_record_hearings(case: Case, record: PortalCase, default_user=None):
    """UYAP duruşmalarını Hearing kayıtlarına eşitler."""
    data = record.data if isinstance(record.data, dict) else {}
    durusmalar = data.get("durusmalar") or []
    from apps.office.models import OfficeSettings

    installed_on = OfficeSettings.load().installed_on
    for item in durusmalar:
        if not isinstance(item, dict):
            continue
        dt_val = parse_hearing_datetime(item.get("tarihSaat") or item.get("durusmaTarihi"))
        if not dt_val:
            continue
        if timezone.localtime(dt_val).date() < installed_on:
            continue  # program kurulmadan önceki duruşmalar aktarılmaz
        portal_ref = str(item.get("kayitId") or item.get("durusmaId") or "").strip()
        auth = str(item.get("yerelBirimAd") or case.authority or "")[:200]
        kind = map_hearing_kind(item.get("islemTuruAciklama") or item.get("tur"))
        result_desc = str(item.get("islemSonucuAciklama") or "").strip()
        status = map_hearing_status(result_desc)
        notes = str(item.get("talepDurumu") or "")

        hearing = None
        if portal_ref:
            hearing = Hearing.objects.filter(case=case, portal_ref=portal_ref).first()
        if not hearing:
            hearing = Hearing.objects.filter(case=case, starts_at=dt_val).first()

        if hearing:
            updates = []
            if portal_ref and hearing.portal_ref != portal_ref:
                hearing.portal_ref = portal_ref
                updates.append("portal_ref")
            if auth and hearing.authority != auth:
                hearing.authority = auth
                updates.append("authority")
            if portal_ref and hearing.portal_ref == portal_ref and hearing.starts_at != dt_val:
                hearing.starts_at = dt_val  # UYAP'ta tarih/saat değiştiyse kayıt onu izler
                updates.append("starts_at")
            if status == HearingStatus.CANCELLED and hearing.status != HearingStatus.CANCELLED:
                hearing.status = HearingStatus.CANCELLED  # UYAP'ta iptal edilen duruşma
                updates.append("status")
            if updates:
                hearing.save(update_fields=updates)
        else:
            Hearing.objects.create(
                case=case,
                kind=kind,
                starts_at=dt_val,
                authority=auth,
                notes=notes,
                status=status,
                portal_ref=portal_ref,
                created_by=case.created_by or default_user,
            )
