"""Görev onay döngüsü.

Aktif → Kontrolde → Onaylandı (aktif) → Kapalı.
Ofis ayarına göre (`OfficeSettings.task_review_mode`):
- `required`: Her zaman kontrolcü onayı zorunludur.
- `assistants_only`: Yalnızca yardımcı personel için kontrolcü onayı zorunludur; avukatlar
  veya kontrolcüsü boş bırakılan görevler doğrudan kapatılabilir.
- `optional`: Kontrolcü boş bırakılabilir; boş bırakılan görevler doğrudan kapatılabilir.
"""

from dataclasses import dataclass

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.accounting.models import LedgerEntry
from apps.cases.documents import publish_task_documents
from apps.cases.models import Case, CaseEvent, Hearing, HearingStatus
from apps.core.permissions import is_admin

from .models import Task, TaskEvent, TaskPoint, TaskStatus

S = TaskStatus


def requires_review(task: Task) -> bool:
    """Bu görevin kapatılmadan önce kontrolcü onayından geçmesinin zorunlu olup olmadığını döner."""
    if not task.reviewer_id:
        return False
    from apps.office.models import OfficeSettings

    mode = OfficeSettings.load().task_review_mode
    return not (
        mode == OfficeSettings.TaskReviewMode.ASSISTANTS_ONLY
        and task.assignee_id
        and task.assignee.is_lawyer_or_above
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
                "points": 2 if task.hearing_id else task.task_type.points,
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
        Action("close", "Görevi kapat", (S.ACTIVE,), S.DONE, "assignee", "closed", "primary"),
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
    return is_admin(user) or user.pk == task.created_by_id


def can_edit(task: Task, user) -> bool:
    """Aktif görevi yalnızca oluşturan, yönetici ve kıdemli avukat düzenler."""
    if task.status != S.ACTIVE or not task.approval_seen:
        return False
    return bool(
        is_admin(user)
        or user.role == user.Role.SENIOR
        or (task.created_by_id and user.pk == task.created_by_id)
    )


@transaction.atomic
def perform(
    task: Task,
    key: str,
    user,
    comment: str = "",
    ledger_id: str = "",
    *,
    hearing_outcome: str = "",
    hearing_decisions: str = "",
    client_informed: bool | None = None,
    client_not_informed_reason: str = "",
    next_hearing_at: str = "",
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
    if key == "close":
        if task.hearing_id:
            next_start = None
            if next_hearing_at:
                try:
                    next_start = forms.DateTimeField().clean(next_hearing_at)
                except ValidationError as exc:
                    raise ValidationError("Yeni duruşma için geçerli tarih ve saat girin.") from exc
                if not task.case_id:
                    raise ValidationError("Yeni duruşma eklemek için dosya gerekli.")
            raw_outcome = hearing_outcome or task.hearing_outcome or "attended"
            hearing_outcome = raw_outcome.strip().lower()
            if hearing_outcome == "excused":
                task.hearing_outcome = "excused"
                task.hearing.excuse_submitted = True
                task.hearing.status = HearingStatus.POSTPONED
                excuse_note = comment or "Duruşmaya mazeret sunuldu."
                if excuse_note:
                    existing_notes = task.hearing.notes.strip()
                    task.hearing.notes = f"{existing_notes}\n[Mazeret]: {excuse_note}".strip()
                task.hearing.save(
                    update_fields=["excuse_submitted", "status", "notes", "updated_at"]
                )
                if not comment:
                    comment = "Mazeret gönderildi."
            else:
                hearing_outcome = "attended"
                decisions = (hearing_decisions or "").strip()
                if not decisions:
                    raise ValidationError("Duruşmada verilen kararları girmelisiniz.")
                if client_informed is None:
                    raise ValidationError("Müvekkile bilgi verilip verilmediğini belirtiniz.")
                reason = (client_not_informed_reason or "").strip()
                if not client_informed and not reason:
                    raise ValidationError("Müvekkile bilgi verilmeme sebebini yazmalısınız.")

                task.hearing_outcome = "attended"
                task.hearing_decisions = decisions
                task.client_informed = client_informed
                task.client_not_informed_reason = reason if not client_informed else ""

                task.hearing.status = HearingStatus.HELD
                task.hearing.decisions = decisions
                task.hearing.result = decisions
                task.hearing.client_informed = client_informed
                task.hearing.client_not_informed_reason = reason if not client_informed else ""
                task.hearing.save(
                    update_fields=[
                        "status",
                        "decisions",
                        "result",
                        "client_informed",
                        "client_not_informed_reason",
                        "updated_at",
                    ]
                )
                if not comment:
                    comment = f"Duruşma yapıldı. Kararlar: {decisions}"
        else:
            if not comment:
                raise ValidationError("Görevi kapatmak için sonuç notu yazmalısınız.")

        if task.case_id and (
            task.requires_accounting or (task.task_type and task.task_type.requires_accounting)
        ):
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
        and task.task_type.requires_document
        and not task.hearing_id
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
    if key in ("submit", "revise", "reopen"):
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
            "hearing_outcome",
            "hearing_decisions",
            "client_informed",
            "client_not_informed_reason",
            "updated_at",
        ]
    )
    TaskEvent.objects.create(
        task=task, actor=user, kind=action.event, from_status=old, to_status=task.status,
        comment=comment,
    )  # fmt: skip

    if key == "close":
        if task.hearing_id and next_start:
            Case.objects.select_for_update().get(pk=task.case_id)
            next_hearing = Hearing.objects.filter(
                case_id=task.case_id, starts_at=next_start
            ).first()
            if next_hearing is None:
                next_hearing = Hearing.objects.create(
                    case_id=task.case_id,
                    starts_at=next_start,
                    client_id=task.client_id,
                    assigned_to_id=task.hearing.assigned_to_id,
                    kind=task.hearing.kind,
                    authority=task.hearing.authority,
                    room=task.hearing.room,
                    created_by=user,
                )
                from apps.agenda.google_sync import queue_hearing_google_sync

                transaction.on_commit(lambda: queue_hearing_google_sync(next_hearing))
        if task.case_id and (
            task.requires_accounting or (task.task_type and task.task_type.requires_accounting)
        ):
            TaskEvent.objects.create(
                task=task,
                actor=user,
                kind=TaskEvent.Kind.NOTE,
                comment=f"Gelir/gider kaydı: {entry.pk} — {entry}",
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
        if task.hearing_id and task.case_id:
            if task.hearing_outcome == "excused":
                CaseEvent.objects.create(
                    case=task.case,
                    date=timezone.localdate(),
                    kind=CaseEvent.Kind.HEARING,
                    title=f"Mazeret bildirildi: {task.hearing.title_display}",
                    description=comment or "Duruşmaya mazeret sunuldu.",
                    created_by=user,
                )
            else:
                info_msg = (
                    "Müvekkile bilgi verildi."
                    if task.client_informed
                    else f"Müvekkile bilgi verilmedi (Sebep: {task.client_not_informed_reason})"
                )
                CaseEvent.objects.create(
                    case=task.case,
                    date=timezone.localdate(),
                    kind=CaseEvent.Kind.HEARING,
                    title=f"Duruşma yapıldı: {task.hearing.title_display}",
                    description=f"Kararlar:\n{task.hearing_decisions}\n\n{info_msg}",
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
