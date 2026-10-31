from django.db import migrations

TASK_TYPES = [
    "Dilekçe",
    "Duruşma hazırlığı",
    "Keşif",
    "Bilirkişi",
    "Tebligat takibi",
    "Harç / Masraf",
    "Müvekkil görüşmesi",
    "İcra takibi",
    "Diğer",
]


def seed(apps, schema_editor):
    TaskType = apps.get_model("office", "TaskType")
    for i, name in enumerate(TASK_TYPES):
        TaskType.objects.get_or_create(name=name, defaults={"order": i})
    OfficeSettings = apps.get_model("office", "OfficeSettings")
    OfficeSettings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("office", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
