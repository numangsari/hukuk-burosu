"""Duruşma gününden 1 gün önce sabah otomatik duruşma ve müvekkil bilgilendirme görevi üretir."""

import datetime as dt
import logging

from django.db import transaction
from django.utils import timezone

from apps.cases.models import CaseStatus, Hearing, HearingStatus
from apps.office.models import HEARING_TASK_TYPE_NAME, TaskType
from apps.tasks.models import Task

log = logging.getLogger(__name__)

TASK_TYPE_NAME = HEARING_TASK_TYPE_NAME


def get_or_create_hearing_task_type() -> TaskType:
    tt = TaskType.objects.filter(name__iexact=TASK_TYPE_NAME).first()
    if tt:
        return tt
    tt, _ = TaskType.objects.get_or_create(
        name=TASK_TYPE_NAME,
        defaults={
            "requires_document": False,
            "categories": ["civil", "criminal", "administrative", "enforcement", "mediation"],
            "points": 2,
        },
    )
    return tt


def create_due_hearing_tasks(reference_date: dt.date | None = None) -> list[Task]:
    """Duruşmadan 1 gün önce (ve duruşma günü) için dosya sorumlusuna otomatik görev oluşturur."""
    today = reference_date or timezone.localdate()
    # Yarınki duruşmalar (1 gün önce sabah) ve bugün henüz görevi açılmamış duruşmalar
    max_date = today + dt.timedelta(days=1)

    hearings = (
        Hearing.objects.filter(
            starts_at__date__gte=today,
            starts_at__date__lte=max_date,
            case__isnull=False,
            case__status=CaseStatus.OPEN,
            status=HearingStatus.PLANNED,
        )
        .select_related("case", "case__client", "case__responsible_lawyer", "assigned_to")
        .order_by("starts_at")
    )

    created_tasks = []
    task_type = None

    for h in hearings:
        if Task.objects.filter(hearing=h).exists():
            continue

        lawyer = h.assigned_to or h.case.responsible_lawyer
        if not lawyer or not lawyer.is_active:
            continue

        if task_type is None:
            task_type = get_or_create_hearing_task_type()

        local_dt = timezone.localtime(h.starts_at)
        title = f"{h.case.display_name} Duruşması İşlemleri Yapılacak ve Müvekkile Bilgi Verilecek"
        due_d = local_dt.date()

        notes = f"Mahkeme / Yer: {h.authority or h.case.authority}\nDuruşma Saati: {local_dt:%H:%M}"
        if h.room:
            notes += f" (Salon: {h.room})"
        if h.notes:
            notes += f"\nDuruşma Notu: {h.notes}"

        with transaction.atomic():
            task = Task(
                task_type=task_type,
                title=title,
                case=h.case,
                client=h.case.client,
                assignee=lawyer,
                reviewer=None,  # Kontrolcüsüz görev
                due_date=due_d,
                notes=notes,
                hearing=h,
                requires_accounting=False,
            )
            task.save()
            created_tasks.append(task)
            log.info("Duruşma görevi oluşturuldu: %s (PK: %s)", task.title, task.pk)

    return created_tasks
