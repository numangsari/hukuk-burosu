from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    """Tamamlanan her aktarım. Aynı Excel dosyasının ikinci kez aktarılmasını engeller."""

    file_sha256 = models.CharField(max_length=64, unique=True)
    file_name = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    counts = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "veri aktarımı"
        verbose_name_plural = "veri aktarımları"

    def __str__(self):
        return f"{self.file_name} ({self.created_at:%d.%m.%Y})"
