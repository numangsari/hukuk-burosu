"""Mevcut görev adlarını büyük harfe çevirir."""

from django.db import migrations

from apps.core.text import tr_upper


def forwards(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    for pk, title in Task.objects.values_list("pk", "title").iterator():
        Task.objects.filter(pk=pk).update(title=tr_upper(title).strip())


class Migration(migrations.Migration):
    dependencies = [("tasks", "0004_task_seen_flags")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
