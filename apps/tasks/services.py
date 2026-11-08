"""Görev onay döngüsü.

Aktif → Kontrolde → Onaylandı (aktif) → Kapalı.
Kontrolcü zorunluluğu rol matrisindeki "tasks.close_without_review" yetkisine bağlıdır:
sorumlunun rolü işaretliyse kontrolcü isteğe bağlıdır ve görev doğrudan kapatılabilir.
"""

import datetime as dt
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.accounting.models import LedgerEntry
from apps.cases.documents import publish_task_documents
from apps.cases.models import CaseEvent
from apps.core.permission_registry import has_perm
from apps.core.permissions import is_admin

from .models import Task, TaskEvent, TaskPoint, TaskStatus

S = TaskStatus

# Görev kapanırken yazılan gelir/gider kaydı notunun başlangıcı (ekranda üstte gösterilir).
LEDGER_NOTE_PREFIX = "Gelir/gider kaydı:"


def requires_review(task: Task) -> bool:
    """Bu görevin kapatılmadan önce kontrolcü onayından geçmesinin zorunlu olup olmadığını döner.

    Sorumlunun rolü "kontrolcü onayı olmadan kapatma" yetkisine sahipse onay zorunlu değildir.
    """
    if not task.reviewer_id:
        return False
    from apps.core.permission_registry import role_has_perm

    return not (
        task.assignee_id and role_has_perm(task.assignee.role, "tasks.close_without_review")
    )


@transaction.atomic
def award_closed_task_points(task):
    """Kapatma işlemi tamamlandığında puanları bir kez kaydeder."""
    from apps.office.models import OfficeSettings

    if not OfficeSettings.load().use_task_points:
        return
    task = Task.objects.select_for_update(of=("self",)).select_related("task_type").get(pk=task.pk)
    if task.status != S.DONE or not task.completed_at:
        raise ValidationError("Puan yalnızca kapatılmış görev için kaydedilebilir.")
    for user_id in {task.assignee_id, task.reviewer_id, task.second_reviewer_id} - {None}:
        TaskPoint.objects.get_or_create(
            task=task,
            user_id=user_id,
            defaults={
                "points": task.task_type.points,
                "earned_at": task.completed_at,
            },
        )


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    sources: tuple
    target: str
    who: str  # assignee / reviewer / manager (oluşturan, kontrolcü)
    event: str
    style: str = "light"
    needs_comment: bool = False


ACTIONS = {
    a.key: a
    for a in [
        Action(
            "submit", "Kontrole gönder", (S.ACTIVE,), S.REVIEW, "assignee", "submitted", "primary"
        ),
        Action("approve", "Onayla", (S.REVIEW,), S.ACTIVE, "reviewer", "approved", "primary"),
        Action(
            "revise",
            "Revizyon iste",
            (S.REVIEW,),
            S.ACTIVE,
            "reviewer",
            "revision",
            "light",
            needs_comment=True,
        ),
        Action("reopen", "Yeniden aç", (S.DONE,), S.ACTIVE, "manager", "reopened"),
        Action("close", "Görevi tamamla", (S.ACTIVE,), S.DONE, "assignee", "closed", "primary"),
    ]
}


def can_do(action: Action, task: Task, user) -> bool:
    if task.status not in action.sources:
        return False
    if action.key == "submit" and (not task.reviewer_id or not task.approval_seen):
        return False
    if action.key in ("approve", "revise") and not task.reviewer_id:
        return False
    if action.key == "close" and task.approval_seen and requires_review(task):
        return False
    if action.who == "assignee":
        # Kontrole yalnızca sorumlu gönderir ve kapatır; kontrolcü ve yönetici yapamaz.
        return user.pk == task.assignee_id
    if action.who == "reviewer":
        # Kontrolde yalnızca sırası gelen kontrolcü onaylar veya revizyon ister.
        return bool(task.active_reviewer_id and user.pk == task.active_reviewer_id)
    # manager (reopen): yönetici de yeniden açabilir.
    if is_admin(user):
        return True
    if task.reviewer_id:
        return user.pk == task.reviewer_id
    return user.pk in (task.assignee_id, task.created_by_id)


def available_actions(task: Task, user) -> list[Action]:
    return [a for a in ACTIONS.values() if can_do(a, task, user)]


def can_upload(task: Task, user) -> bool:
    """Aktif görevde sorumlu, kontrolcü ve yönetici belge yükleyebilir."""
    return (
        task.status == S.ACTIVE
        and task.approval_seen
        and (
            is_admin(user)
            or user.pk in (task.assignee_id, task.reviewer_id, task.second_reviewer_id)
        )
    )


def can_delete(task: Task, user) -> bool:
    return has_perm(user, "tasks.delete_any") or user.pk == task.created_by_id


def can_edit(task: Task, user) -> bool:
    """Aktif görevi oluşturan ve "tasks.edit_any" yetkisi olan roller düzenler."""
    if task.status != S.ACTIVE or not task.approval_seen:
        return False
    return bool(
        has_perm(user, "tasks.edit_any") or (task.created_by_id and user.pk == task.created_by_id)
    )


@transaction.atomic
def perform(
    task: Task,
    key: str,
    user,
    comment: str = "",
    ledger_id: str = "",
    *,
    work_order_no: str = "",
    receipt_no: str = "",
) -> Task:
    action = ACTIONS.get(key)
    if action is None:
        raise ValidationError("Geçersiz işlem.")
    task.refresh_from_db(from_queryset=Task.objects.select_for_update(of=("self",)))
    if task.status not in action.sources:
        raise ValidationError("Görevin durumu değişmiş. Sayfayı yenileyip tekrar deneyin.")
    if not can_do(action, task, user):
        raise PermissionDenied("Bu işlemi yapma yetkiniz yok.")
    comment = (comment or "").strip()
    if key == "submit" and not comment:
        raise ValidationError("Kontrole gönderirken görev notu yazmalısınız.")
    if key == "close":
        work_order_no = (work_order_no or "").strip()
        receipt_no = (receipt_no or "").strip()
        if len(work_order_no) > 60 or len(receipt_no) > 60:
            raise ValidationError("İş emri ve makbuz numarası en çok 60 karakter olabilir.")
        # İş emri no dilekçeli, makbuz no gelir/gider kayıtlı görevlerde tutulur (zorunlu değil).
        task.work_order_no = work_order_no if task.needs_document else ""
        task.receipt_no = receipt_no if task.needs_accounting else ""
        if not comment:
            raise ValidationError("Görevi kapatmak için sonuç notu yazmalısınız.")

        if task.case_id and task.needs_accounting:
            entry = (
                LedgerEntry.objects.filter(
                    pk=ledger_id if str(ledger_id).isdigit() else 0,
                    is_cancelled=False,
                    client_id=task.client_id,
                )
                .filter(models.Q(case_id=task.case_id) | models.Q(case__isnull=True))
                .first()
            )
            if not entry:
                raise ValidationError("Dosyaya veya müvekkile ait geçerli gelir/gider kaydı seçin.")
    if action.needs_comment and not comment:
        raise ValidationError("Revizyon isterken açıklama yazmalısınız.")
    if (
        key in ("submit", "approve", "close")
        and task.needs_document
        and not task.documents.filter(is_current=True, kind="petition").exists()
    ):
        raise ValidationError(
            f'"{task.task_type}" türündeki görev için dilekçe zorunludur. '
            "Belgeyi aktif görevde yükleyip yeniden deneyin."
        )
    task.warnings = []

    old = task.status
    if key == "approve" and task.second_reviewer_id and task.review_step == 1:
        # 1. kontrolcü onayı: görev 2. kontrolcüye geçer, henüz sorumluya dönmez.
        task.review_step = 2
        task.save(update_fields=["review_step", "updated_at"])
        TaskEvent.objects.create(
            task=task, actor=user, kind=action.event, from_status=old, to_status=old,
            comment=comment or "1. kontrol onaylandı; 2. kontrolcüye geçti.",
        )  # fmt: skip
        return task
    was_unapproved = task.approval_seen
    task.status = action.target
    if key == "submit":
        # 2. kontrolcü revize verdiyse görev yeniden doğrudan ona gider; yoksa 1. kontrolcüye.
        task.review_step = 2 if (task.second_reviewer_id and task.review_step == 2) else 1
    elif key == "reopen":
        task.review_step = 1
    task.completed_at = timezone.now() if action.target == S.DONE else None
    if key == "revise":
        task.revision_requested = True
    elif key in ("approve", "reopen"):
        task.revision_requested = False
    # Onaylanan görev sorumlunun ana sayfasında "Onaylandı" olarak görünür.
    task.approval_seen = key != "approve"
    # Onay döngüsüne giren görev artık "yeni" değildir (yeni ve revizyon birlikte görünmez).
    task.assignee_seen = True
    task.save(
        update_fields=[
            "status",
            "completed_at",
            "revision_requested",
            "approval_seen",
            "assignee_seen",
            "review_step",
            "work_order_no",
            "receipt_no",
            "updated_at",
        ]
    )
    TaskEvent.objects.create(
        task=task, actor=user, kind=action.event, from_status=old, to_status=task.status,
        comment=comment,
    )  # fmt: skip

    if key == "close":
        if task.case_id and task.needs_accounting:
            TaskEvent.objects.create(
                task=task,
                actor=user,
                kind=TaskEvent.Kind.NOTE,
                comment=f"{LEDGER_NOTE_PREFIX} {entry.pk} — {entry}",
            )
        if was_unapproved:
            docs, task.warnings = publish_task_documents(task, user)
            names = ", ".join(d.title for d in docs)
            if task.case_id:
                CaseEvent.objects.create(
                    case=task.case,
                    date=timezone.localdate(),
                    kind=CaseEvent.Kind.TASK,
                    title=f"Görev tamamlandı: {task.title}",
                    description=f"{task.assignee}" + (f" · belgeler: {names}" if names else ""),
                    created_by=user,
                )
        award_closed_task_points(task)
    elif key == "reopen":
        task.points_awarded.all().delete()

    if key == "approve":
        docs, task.warnings = publish_task_documents(task, user)
        names = ", ".join(d.title for d in docs)
        if task.case_id:
            CaseEvent.objects.create(
                case=task.case,
                date=timezone.localdate(),
                kind=CaseEvent.Kind.TASK,
                title=f"Görev onaylandı: {task.title}",
                description=f"{task.assignee} · onaylayan {user}"
                + (f" · belgeler: {names}" if names else ""),
                created_by=user,
            )
    return task


def _mark_new_for_assignee(task: Task, user):
    """Görevi başkası atadıysa sorumlu açana kadar "Yeni görev" uyarısı gösterilir.
    Yeni sorumlu için görev sıfırdan başlar: önceki revizyon işareti kalkar (not geçmişte
    kalır), böylece bir görev aynı anda hem "yeni" hem "revizyonlu" görünmez."""
    fields = {"assignee_seen": False, "revision_requested": False}
    Task.objects.filter(pk=task.pk).update(**fields)
    for name, value in fields.items():
        setattr(task, name, value)


def on_created(task: Task, user):
    TaskEvent.objects.create(
        task=task, actor=user, kind=TaskEvent.Kind.CREATED, to_status=task.status
    )
    _mark_new_for_assignee(task, user)


def on_updated(task: Task, user, changed: list[str], old_assignee_id=None):
    if not changed:
        return
    TaskEvent.objects.create(
        task=task, actor=user, kind=TaskEvent.Kind.UPDATED,
        comment="Değişen alanlar: " + ", ".join(changed),
    )  # fmt: skip
    if old_assignee_id and old_assignee_id != task.assignee_id:
        _mark_new_for_assignee(task, user)


def add_comment(task: Task, user, comment: str):
    comment = (comment or "").strip()
    if not comment:
        raise ValidationError("Yorum boş olamaz.")
    TaskEvent.objects.create(task=task, actor=user, kind=TaskEvent.Kind.COMMENT, comment=comment)


EXCUSE_TASK_TYPE = "Mazeret Dilekçesi"


def ensure_excuse_task(hearing, user):
    """Katılma durumu "mazeret" olan duruşma için sorumluya mazeret dilekçesi görevi açar.

    Son gün duruşmadan bir gün öncedir (geçmişe düşerse bugün), kontrolcü yoktur. Aynı duruşma
    için görev bir kez açılır. Sorumlu bulunamazsa görev açılmaz ve None döner.
    """
    from apps.accounts.models import User
    from apps.office.models import TaskType

    if not hearing.case_id:
        return None
    task_type, _ = TaskType.objects.get_or_create(
        name=EXCUSE_TASK_TYPE, defaults={"points": 1, "requires_document": False}
    )
    if Task.objects.filter(hearing=hearing, task_type=task_type).exists():
        return None
    case = hearing.case
    # Sorumlu yönetici olamaz: duruşmanın sorumlu avukatı, yoksa dosyanın yardımcı/avukatı.
    candidates = [hearing.assigned_to, case.responsible_intern, case.responsible_lawyer]
    assignee = next(
        (u for u in candidates if u and u.is_active and u.role != User.Role.ADMIN), None
    )
    if assignee is None:
        return None
    today = timezone.localdate()
    due = max(timezone.localtime(hearing.starts_at).date() - dt.timedelta(days=1), today)
    kind = hearing.get_kind_display().lower()
    with transaction.atomic():
        task = Task.objects.create(
            task_type=task_type,
            title=f"Mazeret dilekçesi gönderilecek ({kind})",
            case=case,
            client=hearing.effective_client or case.client,
            assignee=assignee,
            reviewer=None,
            due_date=due,
            hearing=hearing,
            created_by=user,
        )
        on_created(task, user)
    return task
