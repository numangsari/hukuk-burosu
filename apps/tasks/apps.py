from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    verbose_name = "Görevler"

    def ready(self):
        from auditlog.registry import auditlog

        from . import models

        auditlog.register(models.Task, exclude_fields=["approval_seen", "assignee_seen"])
        auditlog.register(models.TaskPoint)
