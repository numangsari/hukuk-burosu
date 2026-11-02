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


class PowerOfAttorneyReview(models.Model):
    """Vekalet listesindeki kullanıcının işlediği satırın kaynağı."""

    source_sha256 = models.CharField(max_length=64)
    source_row = models.PositiveIntegerField()
    source_reference = models.TextField("kaynak vekalet numarası", blank=True)
    source_note = models.TextField("kaynak notu", blank=True)
    automatic = models.BooleanField("otomatik öneriyle aktarıldı", default=False)
    expected_clients = models.PositiveIntegerField("satırdaki müvekkil sayısı", default=1)
    client = models.ForeignKey(
        "clients.Client", on_delete=models.SET_NULL, null=True, related_name="imported_poa_rows"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "vekalet listesi incelemesi"
        verbose_name_plural = "vekalet listesi incelemeleri"
        constraints = [
            models.UniqueConstraint(
                fields=["source_sha256", "source_row"], name="unique_poa_review_source_row"
            )
        ]

    def __str__(self):
        return f"Vekalet listesi satır {self.source_row}"


class PowerOfAttorneyReviewMember(models.Model):
    """Aynı vekalet satırındaki diğer müvekkiller."""

    review = models.ForeignKey(
        PowerOfAttorneyReview, on_delete=models.CASCADE, related_name="members"
    )
    client = models.ForeignKey(
        "clients.Client", on_delete=models.SET_NULL, null=True, related_name="imported_poa_members"
    )

    class Meta:
        verbose_name = "vekalet listesi ek müvekkili"
        verbose_name_plural = "vekalet listesi ek müvekkilleri"
        constraints = [
            models.UniqueConstraint(fields=["review", "client"], name="unique_poa_review_member")
        ]

    def __str__(self):
        return f"Vekalet listesi satır {self.review.source_row} ek müvekkili"
