"""Dosya durumu işlemleri: aşama değiştirme, kapatma, yeniden açma.

Her işlem dosya satırını kilitler ve zaman çizelgesine kayıt düşer.
"""

from django.db import transaction
from django.utils import timezone

from . import stages
from .models import Case, CaseEvent, CaseFlow, CaseStatus


class StatusError(Exception):
    """Dosyanın o anki durumuna uymayan işlem."""


def _locked(case):
    return Case.objects.select_for_update().get(pk=case.pk)


def _event(case, user, title, description=""):
    CaseEvent.objects.create(
        case=case,
        date=timezone.localdate(),
        kind=CaseEvent.Kind.STATUS,
        title=title,
        description=description,
        created_by=user,
    )


@transaction.atomic
def change_stage(case, stage, user):
    case = _locked(case)
    if not case.is_open:
        raise StatusError("Kapalı dosyanın aşaması değiştirilemez; önce yeniden açılmalıdır.")
    if stage not in dict(stages.open_stages(case.case_type)):
        raise StatusError("Bu dosya türü için geçersiz aşama.")
    if stage == case.stage:
        return case
    old = case.stage_label
    case.stage = stage
    case.save(update_fields=["stage", "updated_at"])
    _event(case, user, f"Aşama değişti: {old} → {case.stage_label}")
    return case


@transaction.atomic
def close_case(case, data, user, collections=None):
    """data: CaseCloseForm.cleaned_data (kapanma nedeni, tarih, karar ve tutar bilgileri)."""
    case = _locked(case)
    if not case.is_open:
        raise StatusError("Dosya zaten kapalı.")
    if collections and case.case_type != "enforcement":
        raise StatusError("Bu tahsilat işlemi yalnızca icra dosyaları içindir.")
    if case.case_type == "enforcement":
        from decimal import Decimal

        from django.core.exceptions import ValidationError

        from apps.cases.forms import ClosingCollectionForm

        validated = []
        for row in collections or []:
            form = ClosingCollectionForm(row)
            if not form.is_valid():
                raise StatusError("Tahsilat satırında geçerli tutar ve tarih girin.")
            if form.cleaned_data["date"] > data["closed_on"]:
                raise StatusError("Tahsilat tarihi kapanış tarihinden sonra olamaz.")
            validated.append(form.cleaned_data)
        total = sum((row["amount"] for row in validated), Decimal("0"))
        if total > Decimal("99999999999999.99"):
            raise StatusError("Tahsilat toplamı izin verilen tutarı aşıyor.")
        data = dict(
            data,
            closing_amount=total or None,
            closing_amount_date=None,
            closing_accounted=True if validated else None,
        )
    case.status = CaseStatus.CLOSED
    case.closing_reason = data["closing_reason"]
    case.closed_on = data["closed_on"]
    case.closing_note = data.get("closing_note", "")
    case.decision_date = data.get("decision_date")
    case.decision_no = data.get("decision_no", "")
    case.closing_amount = data.get("closing_amount")
    case.closing_amount_date = data.get("closing_amount_date")
    case.closing_accounted = data.get("closing_accounted") if case.closing_amount else None
    case.save()
    lines = []
    if case.decision_date or case.decision_no:
        decision = " ".join(
            part
            for part in (
                f"{case.decision_date:%d.%m.%Y}" if case.decision_date else "",
                f"No: {case.decision_no}" if case.decision_no else "",
            )
            if part
        )
        lines.append(f"Karar: {decision}")
    if case.closing_amount:
        when = f" ({case.closing_amount_date:%d.%m.%Y})" if case.closing_amount_date else ""
        accounted = "muhasebeye kaydedildi" if case.closing_accounted else "muhasebeye kaydedilmedi"
        lines.append(f"Tutar: {case.closing_amount:,.2f} TL{when}, {accounted}")
    if case.closing_note:
        lines.append(case.closing_note)
    event = CaseEvent.objects.create(
        case=case,
        date=timezone.localdate(),
        kind=CaseEvent.Kind.STATUS,
        title=f"Dosya kapatıldı: {case.closing_label}",
        description="\n".join(lines),
        created_by=user,
    )
    if case.case_type == "enforcement":
        from apps.accounting.models import EntryKind, LedgerEntry
        from apps.accounting.services import create_entry

        try:
            for row in validated:
                entry = LedgerEntry(
                    client=case.client,
                    case=case,
                    kind=EntryKind.TRUST_IN,
                    amount=row["amount"],
                    date=row["date"],
                    description=row["description"] or "İcra dosyası kapanış tahsilatı",
                    closing_event=event,
                )
                entry.full_clean()
                create_entry(entry)
        except ValidationError as error:
            raise StatusError(" ".join(error.messages)) from error
    return case


@transaction.atomic
def reopen_case(case, stage, user):
    case = _locked(case)
    if case.is_open:
        raise StatusError("Dosya zaten açık.")
    if stage not in dict(stages.open_stages(case.case_type)):
        raise StatusError("Bu dosya türü için geçersiz aşama.")
    previous = case.closing_label
    case.status = CaseStatus.OPEN
    case.stage = stage
    case.closing_reason = ""
    case.closing_note = ""
    case.closed_on = None
    case.decision_date = None
    case.decision_no = ""
    case.closing_amount = None
    case.closing_amount_date = None
    case.closing_accounted = None
    case.save()
    _event(case, user, f"Dosya yeniden açıldı: {case.stage_label}", f"Önceki kapanış: {previous}")
    return case


def flow_members(case):
    """Ortak safahattaki dosyalar (sıralı); bağlı dosyası yoksa yalnızca kendisi."""
    if not case.flow_id:
        return [case]
    return list(
        Case.objects.filter(flow_id=case.flow_id)
        .select_related("client", "responsible_lawyer")
        .order_by("flow_position", "opened_on", "pk")
    )


def _renumber(members):
    for position, member in enumerate(members, start=1):
        if member.flow_position != position:
            Case.objects.filter(pk=member.pk).update(flow_position=position)
            member.flow_position = position


def _event_pair(left, right, user, text):
    for one, other in ((left, right), (right, left)):
        _event(one, user, f"{text}: {other.archive_reference} {other.display_name}")


@transaction.atomic
def link_cases(case, other, note, user):
    """İki dosyayı bağlar; safahat ve muhasebeleri ortak olur (zincir bağlantılar tek grupta).
    İki dosyanın en az bir ortak müvekkili olmalıdır."""
    locked = {c.pk: c for c in Case.objects.select_for_update().filter(pk__in=[case.pk, other.pk])}
    a, b = locked[case.pk], locked[other.pk]
    if a.pk == b.pk:
        raise StatusError("Bir dosya kendisine bağlanamaz.")
    if not (a.client_ids() & b.client_ids()):
        raise StatusError("Bağlanacak dosyaların en az bir ortak müvekkili olmalıdır.")
    if a.flow_id and a.flow_id == b.flow_id:
        raise StatusError("Bu dosyalar zaten bağlı.")
    sequence = flow_members(a) + flow_members(b)
    flow_id = a.flow_id or b.flow_id or CaseFlow.objects.create().pk
    for old in {a.flow_id, b.flow_id} - {None, flow_id}:
        Case.objects.filter(flow_id=old).update(flow_id=flow_id)
    Case.objects.filter(pk__in=[m.pk for m in sequence]).update(flow_id=flow_id)
    for member in sequence:
        member.flow_id = flow_id
    _renumber(sequence)
    Case.objects.filter(pk=b.pk).update(flow_note=(note or "").strip())
    _event_pair(a, b, user, "Dosya bağlandı")
    return flow_id


@transaction.atomic
def unlink_case(case, user):
    """Dosyanın bağlantısını koparır; geri kalan tek dosya kalırsa grup dağılır."""
    locked = Case.objects.select_for_update().get(pk=case.pk)
    if not locked.flow_id:
        raise StatusError("Dosya başka bir dosyaya bağlı değil.")
    remaining = [m for m in flow_members(locked) if m.pk != locked.pk]
    Case.objects.filter(pk=locked.pk).update(flow=None, flow_position=0, flow_note="")
    if len(remaining) <= 1:
        Case.objects.filter(pk__in=[m.pk for m in remaining]).update(
            flow=None, flow_position=0, flow_note=""
        )
    else:
        _renumber(remaining)
    for member in remaining:
        _event(
            member, user, f"Bağlantı koparıldı: {locked.archive_reference} {locked.display_name}"
        )
    _event(locked, user, "Bağlantı koparıldı: dosya ortak safahattan ayrıldı")


def dissolve_if_single(flow_id):
    """Silme sonrası grupta tek dosya kaldıysa grubu dağıtır."""
    if not flow_id:
        return
    left = list(Case.objects.filter(flow_id=flow_id))
    if len(left) <= 1:
        Case.objects.filter(flow_id=flow_id).update(flow=None, flow_position=0, flow_note="")


@transaction.atomic
def move_member(case, direction):
    """Dosyanın ortak akıştaki sırasını bir yukarı ("up") veya aşağı ("down") değiştirir."""
    locked = Case.objects.select_for_update().get(pk=case.pk)
    members = flow_members(locked)
    index = next(i for i, m in enumerate(members) if m.pk == locked.pk)
    other = index - 1 if direction == "up" else index + 1
    if not locked.flow_id or other < 0 or other >= len(members):
        return False
    members[index], members[other] = members[other], members[index]
    _renumber(members)
    return True
