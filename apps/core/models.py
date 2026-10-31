from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Oluşturma/güncelleme zamanı ve oluşturan kullanıcıyı tutan soyut model."""

    created_at = models.DateTimeField("oluşturulma", auto_now_add=True)
    updated_at = models.DateTimeField("güncellenme", auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="oluşturan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True
