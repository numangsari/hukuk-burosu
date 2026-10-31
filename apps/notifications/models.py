from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Sistem içi bildirim (üst çubuktaki zil)."""

    class Kind(models.TextChoices):
        TASK = "task", "Görev"
        DEADLINE = "deadline", "Son gün"
        HEARING = "hearing", "Duruşma"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.TASK)
    title = models.CharField(max_length=300)
    body = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=300, blank=True)
    # Aynı hatırlatmanın iki kez gönderilmesini önler (ör. "due:12:2026-11-02").
    key = models.CharField(max_length=100, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["user", "is_read"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key"], condition=~models.Q(key=""), name="unique_notification_key"
            )
        ]

    def __str__(self):
        return self.title
