from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import Case
from apps.clients.models import Client
from apps.core.models import TimeStampedModel
from apps.core.text import fold, tr_upper
from apps.office.models import TaskType


class TaskStatus(models.TextChoices):
    ACTIVE = "active", "Aktif"
    REVIEW = "review", "Kontrolde"
    DONE = "done", "Kapalı"


OPEN_STATUSES = [TaskStatus.ACTIVE, TaskStatus.REVIEW]


class RoutineTask(TimeStampedModel):
    """Haftanın belli günü veya ayın belli günü kendiliğinden ofis içi görev açan kural."""

    class Frequency(models.TextChoices):
        WEEKLY = "weekly", "Her hafta"
        MONTHLY = "monthly", "Her ay"

    WEEKDAYS = [
        (0, "Pazartesi"),
        (1, "Salı"),
        (2, "Çarşamba"),
        (3, "Perşembe"),
        (4, "Cuma"),
        (5, "Cumartesi"),
        (6, "Pazar"),
    ]

    title = models.CharField("görev adı", max_length=300)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="sorumlu",
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"is_active": True},
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="kontrolcü",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"is_active": True},
    )
    frequency = models.CharField(
        "sıklık", max_length=10, choices=Frequency.choices, default=Frequency.WEEKLY
    )
    weekday = models.PositiveSmallIntegerField("haftanın günü", null=True, blank=True)
    month_day = models.PositiveSmallIntegerField("ayın günü", null=True, blank=True)
    due_days = models.PositiveSmallIntegerField(
        "süre (gün)",
        default=0,
        help_text="Görev açıldığı günden kaç gün sonra bitmeli (0 = aynı gün).",
    )
    is_active = models.BooleanField("etkin", default=True)
    last_created_for = models.DateField(
        "son oluşturulan gün", null=True, blank=True, editable=False
    )

    class Meta:
        verbose_name = "rutin görev"
        verbose_name_plural = "rutin görevler"
        ordering = ["title", "pk"]

    def __str__(self):
        return self.title

    @property
    def schedule_label(self) -> str:
        if self.frequency == self.Frequency.WEEKLY:
            return f"Her hafta {dict(self.WEEKDAYS).get(self.weekday, '?')}"
        return f"Her ayın {self.month_day}. günü"


class Task(TimeStampedModel):
    task_type = models.ForeignKey(
        TaskType, verbose_name="görev türü", on_delete=models.PROTECT, related_name="tasks"
    )
    title = models.CharField("görev adı", max_length=300)
    # Dosyası olmayan görev "ofis içi görev"dir: yalnızca sorumlu, kontrolcü ve yönetici görür.
    case = models.ForeignKey(
        Case,
        verbose_name="dosya",
        on_delete=models.PROTECT,
        related_name="tasks",
        null=True,
        blank=True,
    )
    # Müvekkil her zaman dosyanın müvekkilidir; save() içinde doldurulur.
    client = models.ForeignKey(
        Client, verbose_name="müvekkil", on_delete=models.PROTECT, related_name="tasks",
        editable=False, null=True,
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
        null=True,
        blank=True,
        related_name="review_tasks",
        limit_choices_to={"is_active": True},
    )
    due_date = models.DateField("son gün")
    work_order_no = models.CharField("iş emri no", max_length=60, blank=True)
    notes = models.TextField("notlar", blank=True)
    requires_accounting = models.BooleanField("gelir/gider kaydı", null=True, blank=True)
    hearing = models.ForeignKey(
        "cases.Hearing",
        verbose_name="bağlı duruşma / etkinlik",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    hearing_outcome = models.CharField("duruşma sonucu türü", max_length=50, blank=True)
    hearing_decisions = models.TextField("duruşma kararları", blank=True)
    client_informed = models.BooleanField("müvekkile bilgi verildi", null=True, blank=True)
    client_not_informed_reason = models.TextField("müvekkile bilgi verilmeme sebebi", blank=True)
    status = models.CharField(
        "durum", max_length=20, choices=TaskStatus.choices, default=TaskStatus.ACTIVE
    )
    # Revizyon istendiğinde işaretlenir; yeniden kontrolde "Revize Edildi" aşamasını korur.
    revision_requested = models.BooleanField("revizyon istendi", default=False)
    # Onaylanan aktif görev, kapatma prosedürü belirlenene kadar "Onaylandı" olarak kalır.
    approval_seen = models.BooleanField("onay görüldü", default=True)
    # Yeni görev, sorumlu açana kadar "Yeni Görev" aşamasında görünür.
    assignee_seen = models.BooleanField("sorumlu gördü", default=True)
    completed_at = models.DateTimeField("tamamlanma", null=True, blank=True)
    # Rutin görev kuralından üretildiyse kural ve ait olduğu gün (aynı gün iki kez açılmaz).
    routine = models.ForeignKey(
        RoutineTask, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    routine_date = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "görev"
        verbose_name_plural = "görevler"
        ordering = ["due_date", "pk"]
        indexes = [models.Index(fields=["status", "due_date"])]
        constraints = [
            models.UniqueConstraint(
                fields=["routine", "routine_date"],
                condition=models.Q(routine__isnull=False),
                name="unique_routine_occurrence",
            )
        ]

    def __str__(self):
        return self.title

    def clean(self):
        if self.assignee_id and self.reviewer_id and self.assignee_id == self.reviewer_id:
            raise ValidationError({"reviewer": "Kontrolcü, sorumludan farklı biri olmalı."})

    def save(self, *args, **kwargs):
        self.title = tr_upper(self.title).strip()  # görev adları büyük harf
        if self.case_id:
            self.client_id = Case.objects.values_list("client_id", flat=True).get(pk=self.case_id)
        else:
            self.client_id = None
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("tasks:detail", args=[self.pk])

    @property
    def is_office_task(self) -> bool:
        return self.case_id is None

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def stage_label(self):
        if self.status == TaskStatus.DONE:
            return ""
        if self.status == TaskStatus.REVIEW:
            return "Revize Edildi" if self.revision_requested else "Kontrolde"
        if not self.assignee_seen:
            return "Yeni Görev"
        if self.revision_requested:
            return "Revize İstendi"
        if not self.approval_seen:
            return "Onaylandı"
        return ""

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
        CLOSED = "closed", "kapattı"
        REOPENED = "reopened", "yeniden açtı"
        UPDATED = "updated", "güncelledi"
        COMMENT = "comment", "yorum yaptı"
        NOTE = "note", "not ekledi"

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


class TaskPoint(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="points_awarded")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="task_points"
    )
    points = models.PositiveSmallIntegerField("puan")
    earned_at = models.DateTimeField("kazanılma zamanı")

    class Meta:
        verbose_name = "görev puanı"
        verbose_name_plural = "görev puanları"
        constraints = [
            models.UniqueConstraint(fields=["task", "user"], name="unique_task_user_point")
        ]

    def __str__(self):
        return f"{self.user} — {self.points}"


def task_document_upload_to(instance, filename):
    from pathlib import Path
    from uuid import uuid4

    name = Path(filename)
    return f"tasks/{instance.task_id}/{uuid4().hex[:8]}_{name.stem[:80]}{name.suffix.lower()}"


class TaskDocument(models.Model):
    """Görev belgesi. Yeni sürüm yüklenince eskisi `is_current=False` olur ve geçmişte kalır."""

    class Kind(models.TextChoices):
        SOURCE = "source", "Görev için eklenen belge"
        PETITION = "petition", "Dilekçe"
        ATTACHMENT = "attachment", "Dilekçe eki"
        LEGACY = "legacy", "Önceki belge"

    kind = models.CharField("belge türü", max_length=12, choices=Kind.choices, default=Kind.LEGACY)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField("belge", upload_to=task_document_upload_to)
    original_name = models.CharField(max_length=300)
    folder_path = models.CharField("klasördeki kopya", max_length=500, blank=True, editable=False)
    size = models.PositiveBigIntegerField(default=0)
    version = models.PositiveSmallIntegerField(default=1)
    previous = models.OneToOneField(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="next_version"
    )
    is_current = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "görev belgesi"
        verbose_name_plural = "görev belgeleri"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.original_name

    @property
    def is_pdf(self) -> bool:
        return self.original_name.lower().endswith(".pdf")


class PetitionSample(TimeStampedModel):
    """Dilekçe havuzu: büronun herkesin görüp indirebileceği hazır dilekçe örnekleri."""

    title = models.CharField("başlık", max_length=200)
    petition_type = models.CharField("dilekçe türü", max_length=80, blank=True)
    description = models.TextField("açıklama", blank=True)
    file = models.FileField("dosya", upload_to="petition-pool/%Y/")
    original_name = models.CharField(max_length=300, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    search_key = models.TextField(editable=False, blank=True)

    class Meta:
        verbose_name = "dilekçe örneği"
        verbose_name_plural = "dilekçe havuzu"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Büyük/küçük harf ve Türkçe karakter farkını yok sayan arama anahtarı.
        self.search_key = fold(f"{self.title} {self.petition_type} {self.description}")
        super().save(*args, **kwargs)
