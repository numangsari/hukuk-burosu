"""Dosya durumu işlemleri: aşama değiştirme, kapatma, yeniden açma.

Her işlem dosya satırını kilitler ve zaman çizelgesine kayıt düşer.
"""

from django.db import transaction
from django.utils import timezone

from . import stages
from .models import Case, CaseEvent, CaseStatus


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
def close_case(case, data, user):
    """data: CaseCloseForm.cleaned_data (kapanma nedeni, tarih, karar ve tutar bilgileri)."""
    case = _locked(case)
    if not case.is_open:
        raise StatusError("Dosya zaten kapalı.")
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
    _event(case, user, f"Dosya kapatıldı: {case.closing_label}", "\n".join(lines))
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


@transaction.atomic
def apply_step_to_case(step, user):
    """Safahat adımındaki kurum adı ve dosya numarasını esas dosyaya yazar."""
    case = _locked(step.case)
    previous = f"{case.authority} {case.official_no}".strip() or "boş"
    case.authority = step.authority
    if step.official_no:
        case.official_no = step.official_no
    case.save(update_fields=["authority", "official_no", "updated_at"])
    _event(
        case,
        user,
        f"Esas dosya bilgisi güncellendi: {case.authority} {case.official_no}".strip(),
        f"Önceki bilgi: {previous}",
    )
    return case
