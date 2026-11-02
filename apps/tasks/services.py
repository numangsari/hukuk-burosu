"""Görev onay döngüsü.

Aktif → Kontrolde → Onaylandı (aktif). Kapatma adımı ayrıca belirlenecek.
Kontrolcü revizyon isterse görev aktif duruma döner ve revizyon işareti alır.
Kapalı görev yeniden açılabilir. Yönetici her işlemi yapabilir; kontrole sorumlu ve
yönetici dışında kimse gönderemez.
İptal durumu yoktur; yanlış açılan görevi oluşturan veya yönetici siler.
"""

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cases.documents import publish_task_documents
from apps.cases.models import CaseEvent
from apps.core.permissions import is_admin

from .models import Task, TaskEvent, TaskPoint, TaskStatus

S = TaskStatus


@transaction.atomic
def award_closed_task_points(task):
    """Kapatma işlemi tamamlandığında puanları bir kez kaydeder."""
    task = Task.objects.select_for_update().select_related("task_type").get(pk=task.pk)
    if task.status != S.DONE or not task.completed_at:
        raise ValidationError("Puan yalnızca kapatılmış görev için kaydedilebilir.")
    for user_id in {task.assignee_id, task.reviewer_id}:
        TaskPoint.objects.get_or_create(
            task=task,
            user_id=user_id,
            defaults={"points": task.task_type.points, "earned_at": task.completed_at},
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
    ]
}


def can_do(action: Action, task: Task, user) -> bool:
    if task.status not in action.sources:
        return False
    if action.key == "submit" and not task.approval_seen:
        return False
    if is_admin(user):
        return True
    if action.who == "assignee":
        # Kontrole sorumlu (ve yönetici) gönderir; kontrolcü gönderemez.
        return user.pk == task.assignee_id
    if action.who == "reviewer":
        return user.pk == task.reviewer_id
    return user.pk in (task.reviewer_id, task.created_by_id)


def available_actions(task: Task, user) -> list[Action]:
    return [a for a in ACTIONS.values() if can_do(a, task, user)]


def can_upload(task: Task, user) -> bool:
    """Aktif görevde sorumlu, kontrolcü ve yönetici belge yükleyebilir."""
    return (
        task.status == S.ACTIVE
        and task.approval_seen
        and (is_admin(user) or user.pk in (task.assignee_id, task.reviewer_id))
    )


def can_delete(task: Task, user) -> bool:
    return is_admin(user) or user.pk == task.created_by_id


def can_edit(task: Task, user) -> bool:
    return (
        task.status == S.ACTIVE
        and task.approval_seen
        and (is_admin(user) or user.pk in (task.created_by_id, task.reviewer_id, task.assignee_id))
    )


@transaction.atomic
def perform(task: Task, key: str, user, comment: str = "") -> Task:
    action = ACTIONS.get(key)
    if action is None:
        raise ValidationError("Geçersiz işlem.")
    task.refresh_from_db(from_queryset=Task.objects.select_for_update())
    if task.status not in action.sources:
        raise ValidationError("Görevin durumu değişmiş. Sayfayı yenileyip tekrar deneyin.")
    if not can_do(action, task, user):
        raise PermissionDenied("Bu işlemi yapma yetkiniz yok.")
    comment = (comment or "").strip()
    if action.needs_comment and not comment:
        raise ValidationError("Revizyon isterken açıklama yazmalısınız.")
    if (
        key in ("submit", "approve")
        and task.task_type.requires_document
        and not task.documents.filter(is_current=True).exists()
    ):
        raise ValidationError(
            f'"{task.task_type}" türündeki görev için belge zorunludur. '
            "Belgeyi aktif görevde yükleyip yeniden kontrole gönderin."
        )
    task.warnings = []

    old = task.status
    task.status = action.target
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
            "updated_at",
        ]
    )
    TaskEvent.objects.create(
        task=task, actor=user, kind=action.event, from_status=old, to_status=task.status,
        comment=comment,
    )  # fmt: skip

    if key == "approve":
        docs, task.warnings = publish_task_documents(task, user)
        names = ", ".join(d.title for d in docs)
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
