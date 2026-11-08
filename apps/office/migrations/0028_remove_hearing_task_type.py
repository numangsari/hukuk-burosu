from django.db import migrations

NAME = "Duruşma Ve Müvekkil Bilgilendirme"


def remove_unused_hearing_task_type(apps, schema_editor):
    """Duruşma görev türü kaldırıldı: hiçbir görev veya rutin kuralı kullanmıyorsa silinir."""
    task_type = apps.get_model("office", "TaskType")
    task = apps.get_model("tasks", "Task")
    routine = apps.get_model("tasks", "RoutineTask")
    for item in task_type.objects.filter(name__iexact=NAME):
        if not task.objects.filter(task_type=item).exists() and not routine.objects.filter(
            task_type=item
        ).exists():
            item.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("office", "0027_installed_on"),
        ("tasks", "0023_receipt_no"),
    ]

    operations = [migrations.RunPython(remove_unused_hearing_task_type, migrations.RunPython.noop)]
