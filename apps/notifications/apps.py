from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    verbose_name = "Bildirimler"

    def ready(self):
        from . import signals  # noqa: F401
