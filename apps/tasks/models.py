from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import Case
from apps.clients.models import Client
from apps.core.models import TimeStampedModel
from apps.office.models import TaskType


class TaskStatus(models.TextChoices):
    ACTIVE = "active", "Aktif"
    REVIEW = "review", "Kontrolde"
    DONE = "done", "Tamamlandı"


OPEN_STATUSES = [TaskStatus.ACTIVE, TaskStatus.REVIEW]


class Task(TimeStampedModel):
    task_type = models.ForeignKey(
        TaskType, verbose_name="görev türü", on_delete=models.PROTECT, related_name="tasks"
    )
    title = models.CharField("görev adı", max_length=300)
    case = models.ForeignKey(
        Case, verbose_name="dosya", on_delete=models.PROTECT, related_name="tasks"
    )
    # Müvekkil her zaman dosyanın müvekkilidir; save() içinde doldurulur.
    client = models.ForeignKey(
        Client, verbose_name="müvekkil", on_delete=models.PROTECT, related_name="tasks",
        editable=False,
    )  # fmt: skip
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="sorumlu",
        on_delete=models.PROTECT,
        related_name="assigned_tasks",
        limit_choices_to={"is_active": True},
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="kontrolcü",
        on_delete=models.PROTECT,
        related_name="review_tasks",
        limit_choices_to={"is_active": True},
    )
    due_date = models.DateField("son gün")
    notes = models.TextField("notlar", blank=True)
    status = models.CharField(
        "durum", max_length=20, choices=TaskStatus.choices, default=TaskStatus.ACTIVE
    )
    # Kontrolcü revizyon istediğinde işaretlenir, sorumlu tekrar kontrole gönderince kalkar.
    revision_requested = models.BooleanField("revizyon istendi", default=False)
    completed_at = models.DateTimeField("tamamlanma", null=True, blank=True)

    class Meta:
        verbose_name = "görev"
        verbose_name_plural = "görevler"
        ordering = ["due_date", "pk"]
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self):
        return self.title

    def clean(self):
        if self.assignee_id and self.assignee_id == self.reviewer_id:
            raise ValidationError({"reviewer": "Kontrolcü, sorumludan farklı biri olmalı."})

    def save(self, *args, **kwargs):
        if self.case_id:
            self.client_id = Case.objects.values_list("client_id", flat=True).get(pk=self.case_id)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("tasks:detail", args=[self.pk])

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def days_left(self) -> int:
        return (self.due_date - timezone.localdate()).days

    @property
    def urgency(self) -> str:
        """overdue / today / soon (≤3 gün) / normal — rozet rengi için."""
        if not self.is_open:
            return "closed"
        d = self.days_left
        if d < 0:
            return "overdue"
        if d == 0:
            return "today"
        if d <= 3:
            return "soon"
        return "normal"

    @property
    def due_label(self) -> str:
        if not self.is_open:
            return self.due_date.strftime("%d.%m.%Y")
        d = self.days_left
        if d < 0:
            return f"{-d} gün gecikti"
        if d == 0:
            return "Bugün"
        if d == 1:
            return "Yarın"
        return f"{d} gün kaldı"


class TaskEvent(models.Model):
    """Görev geçmişi: durum geçişleri, düzenlemeler ve yorumlar."""

    class Kind(models.TextChoices):
        CREATED = "created", "oluşturdu"
        SUBMITTED = "submitted", "kontrole gönderdi"
        APPROVED = "approved", "onayladı"
        REVISION = "revision", "revizyon istedi"
        REOPENED = "reopened", "yeniden açtı"
        UPDATED = "updated", "güncelledi"
        COMMENT = "comment", "yorum yaptı"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    from_status = models.CharField(max_length=20, choices=TaskStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=TaskStatus.choices, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.actor} {self.get_kind_display()}"
