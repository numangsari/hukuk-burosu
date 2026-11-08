"""Rutin görevler: haftalık / aylık kurallardan ofis içi görev üretir."""

import calendar
import datetime as dt
import logging

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.cases.documents import mirror_task_document
from apps.core.permission_registry import role_has_perm
from apps.office.models import TaskType

from . import services
from .models import RoutineTask, Task, TaskDocument, TaskEvent

ROUTINE_TYPE_NAME = "Rutin Görev"
# Sunucu kapalı kaldıysa kaçan gün en çok bu kadar geriye dönük açılır.
CATCH_UP_DAYS = 3

log = logging.getLogger(__name__)


def _month_day(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def latest_occurrence(routine: RoutineTask, today: dt.date) -> dt.date | None:
    """Kuralın `today` dahil en son gelen gününü döner."""
    if routine.frequency == RoutineTask.Frequency.WEEKLY:
        if routine.weekday is None:
            return None
        return today - dt.timedelta(days=(today.weekday() - routine.weekday) % 7)
    if routine.month_day is None:
        return None
    candidate = _month_day(today.year, today.month, routine.month_day)
    if candidate <= today:
        return candidate
    year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return _month_day(year, month, routine.month_day)


def routine_task_type() -> TaskType:
    task_type, _ = TaskType.objects.get_or_create(
        name=ROUTINE_TYPE_NAME,
        defaults={"categories": ["Ofis İçi İşlemler"], "points": 0},
    )
    return task_type


def copy_routine_extras(routine: RoutineTask, task: Task) -> None:
    """Kuraldaki notu ve belgeleri yeni açılan göreve aktarır."""
    if routine.notes.strip():
        TaskEvent.objects.create(
            task=task,
            actor=routine.created_by,
            kind=TaskEvent.Kind.NOTE,
            comment=routine.notes.strip(),
        )
    for source in routine.documents.all():
        try:
            with source.file.open("rb") as handle:
                content = ContentFile(handle.read())
        except OSError:
            continue  # dosyası kaybolmuş belge görevin açılmasını engellemez
        doc = TaskDocument(
            task=task,
            kind=TaskDocument.Kind.SOURCE,
            original_name=source.original_name,
            size=source.size,
            uploaded_by=routine.created_by,
        )
        doc.file.save(source.original_name, content, save=False)
        doc.save()

        def mirror(doc=doc):
            mirror_task_document(doc)

        transaction.on_commit(mirror)


def create_due_tasks(today: dt.date | None = None) -> tuple[int, int]:
    """Günü gelen rutin kuralların görevlerini bir kez oluşturur: (oluşturulan, atlanan)."""
    today = today or timezone.localdate()
    created = skipped = 0
    for routine in (
        RoutineTask.objects.filter(is_active=True)
        .select_related("assignee", "reviewer", "second_reviewer", "task_type", "case")
        .prefetch_related("documents")
    ):
        occurrence = latest_occurrence(routine, today)
        if occurrence is None or occurrence < today - dt.timedelta(days=CATCH_UP_DAYS):
            continue
        if occurrence <= (routine.last_created_for or today - dt.timedelta(days=1)):
            continue
        if not routine.assignee.is_active:
            skipped += 1
            continue
        reviewer = routine.reviewer if routine.reviewer and routine.reviewer.is_active else None
        if (
            routine.reviewer_id
            and reviewer is None
            and not role_has_perm(routine.assignee.role, "tasks.close_without_review")
        ):
            # Kontrolcü pasifleşmiş ve sorumlu onaysız kapatamıyor: görev kontrolcüsüz açılmaz.
            log.warning("Rutin görev #%s atlandı: etkin kontrolcü yok.", routine.pk)
            skipped += 1
            continue
        second = routine.second_reviewer
        second = second if reviewer and second and second.is_active else None
        try:
            with transaction.atomic():
                task = Task.objects.create(
                    task_type=routine.task_type or routine_task_type(),
                    title=routine.title,
                    case=routine.case,
                    assignee=routine.assignee,
                    reviewer=reviewer,
                    second_reviewer=second,
                    requires_accounting=bool(routine.case_id and routine.needs_accounting),
                    requires_document=routine.needs_document,
                    due_date=occurrence + dt.timedelta(days=routine.due_days),
                    routine=routine,
                    routine_date=occurrence,
                    created_by=routine.created_by,
                )
                services.on_created(task, routine.created_by)
                copy_routine_extras(routine, task)
        except IntegrityError:
            pass  # aynı gün başka bir çalıştırma açmış
        else:
            created += 1
        RoutineTask.objects.filter(pk=routine.pk).update(last_created_for=occurrence)
    return created, skipped
