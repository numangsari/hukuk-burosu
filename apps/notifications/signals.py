"""Tarih veya sorumlu değişikliklerinden sonra hatırlatmalar yeniden taransın."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .services import invalidate_reminders


@receiver(post_save, sender="tasks.Task")
@receiver(post_delete, sender="tasks.Task")
@receiver(post_save, sender="cases.Hearing")
@receiver(post_delete, sender="cases.Hearing")
@receiver(post_save, sender="cases.Service")
@receiver(post_delete, sender="cases.Service")
@receiver(post_save, sender="cases.Case")
def refresh_reminders(sender, **kwargs):
    if not kwargs.get("raw", False):
        transaction.on_commit(invalidate_reminders)
