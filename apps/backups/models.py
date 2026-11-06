from django.db import models


class BackupRecord(models.Model):
    class Status(models.TextChoices):
        OK = "ok", "Başarılı"
        ERROR = "error", "Hatalı"

    class Kind(models.TextChoices):
        SCHEDULED = "scheduled", "Zamanlanmış"
        MANUAL = "manual", "Elle"
        UPDATE = "update", "Güncelleme öncesi"
        PRE_RESTORE = "pre_restore", "Geri yükleme öncesi"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SCHEDULED)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ERROR)
    file_name = models.CharField(max_length=200, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    copied_to = models.CharField(max_length=500, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "yedek"
        verbose_name_plural = "yedekler"

    def __str__(self):
        return self.file_name or f"Yedek {self.started_at:%d.%m.%Y %H:%M}"
