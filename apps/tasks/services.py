"""Görev onay döngüsü.

Aktif → Kontrolde → Tamamlandı
Kontrolcü revizyon isterse görev Aktif'e döner ve "revizyon istendi" işareti alır.
Tamamlanan görev yeniden açılabilir. Yönetici her işlemi yapabilir.
İptal durumu yoktur; yanlış açılan görevi oluşturan veya yönetici siler.
"""

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cases.documents import publish_task_documents
from apps.cases.models import CaseEvent
from apps.core.permissions import is_admin
from apps.notifications.services import notify

from .models import Task, TaskEvent, TaskStatus

S = TaskStatus


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
        Action("approve", "Onayla", (S.REVIEW,), S.DONE, "reviewer", "approved", "primary"),
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
    if is_admin(user):
        return True
    if action.who == "assignee":
        return user.pk == task.assignee_id
    if action.who == "reviewer":
        return user.pk == task.reviewer_id
    return user.pk in (task.reviewer_id, task.created_by_id)


def available_actions(task: Task, user) -> list[Action]:
    return [a for a in ACTIONS.values() if can_do(a, task, user)]


def can_upload(task: Task, user) -> bool:
    """Açık görevde sorumlu, kontrolcü ve yönetici belge yükleyebilir."""
    return task.is_open and (is_admin(user) or user.pk in (task.assignee_id, task.reviewer_id))


def can_delete(task: Task, user) -> bool:
    return is_admin(user) or user.pk == task.created_by_id


def can_edit(task: Task, user) -> bool:
    return task.is_open and (
        is_admin(user) or user.pk in (task.created_by_id, task.reviewer_id, task.assignee_id)
    )


@transaction.atomic
def perform(task: Task, key: str, user, comment: str = "") -> Task:
    action = ACTIONS.get(key)
    if action is None:
        raise ValidationError("Geçersiz işlem.")
    if not can_do(action, task, user):
        raise PermissionDenied("Bu işlemi yapma yetkiniz yok.")
    comment = (comment or "").strip()
    if action.needs_comment and not comment:
        raise ValidationError("Revizyon isterken açıklama yazmalısınız.")
    if (
        key == "submit"
        and task.task_type.requires_document
        and not task.documents.filter(is_current=True).exists()
    ):
        raise ValidationError(
            f'"{task.task_type}" türündeki görevi kontrole göndermeden önce belge yüklemelisiniz.'
        )
    task.warnings = []

    old = task.status
    task.status = action.target
    task.completed_at = timezone.now() if action.target == S.DONE else None
    if key == "revise":
        task.revision_requested = True
    elif key in ("submit", "reopen"):
        task.revision_requested = False
    task.save(update_fields=["status", "completed_at", "revision_requested", "updated_at"])
    TaskEvent.objects.create(
        task=task, actor=user, kind=action.event, from_status=old, to_status=task.status,
        comment=comment,
    )  # fmt: skip

    url = task.get_absolute_url()
    if key == "submit":
        notify(task.reviewer, f"Kontrolünüzü bekliyor: {task.title}", url=url, actor=user)
    elif key == "approve":
        notify(task.assignee, f"Görev onaylandı: {task.title}", url=url, actor=user)
        docs, task.warnings = publish_task_documents(task, user)
        names = ", ".join(d.title for d in docs)
        CaseEvent.objects.create(
            case=task.case,
            date=timezone.localdate(),
            kind=CaseEvent.Kind.TASK,
            title=f"Görev tamamlandı: {task.title}",
            description=f"{task.assignee} · onaylayan {user}"
            + (f" · belgeler: {names}" if names else ""),
            created_by=user,
        )
    elif key == "revise":
        notify(
            task.assignee,
            f"Revizyon istendi: {task.title}",
            body=comment[:200],
            url=url,
            actor=user,
        )
    elif key == "reopen":
        notify(task.assignee, f"Görev yeniden açıldı: {task.title}", url=url, actor=user)
    return task


def on_created(task: Task, user):
    TaskEvent.objects.create(
        task=task, actor=user, kind=TaskEvent.Kind.CREATED, to_status=task.status
    )
    notify(
        task.assignee,
        f"Size yeni görev atandı: {task.title}",
        url=task.get_absolute_url(),
        actor=user,
    )


def on_updated(task: Task, user, changed: list[str], old_assignee_id=None):
    if not changed:
        return
    TaskEvent.objects.create(
        task=task, actor=user, kind=TaskEvent.Kind.UPDATED,
        comment="Değişen alanlar: " + ", ".join(changed),
    )  # fmt: skip
    if old_assignee_id and old_assignee_id != task.assignee_id:
        notify(
            task.assignee,
            f"Size görev atandı: {task.title}",
            url=task.get_absolute_url(),
            actor=user,
        )


def add_comment(task: Task, user, comment: str):
    comment = (comment or "").strip()
    if not comment:
        raise ValidationError("Yorum boş olamaz.")
    TaskEvent.objects.create(task=task, actor=user, kind=TaskEvent.Kind.COMMENT, comment=comment)
    for other in {task.assignee, task.reviewer}:
        notify(
            other,
            f"Yeni yorum: {task.title}",
            body=comment[:200],
            url=task.get_absolute_url(),
            actor=user,
        )
