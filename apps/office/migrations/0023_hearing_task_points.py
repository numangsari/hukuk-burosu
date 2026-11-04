from django.db import migrations


def set_hearing_task_points(apps, schema_editor):
    task_type = apps.get_model("office", "TaskType")
    task_type.objects.filter(name__iexact="Duruşma Ve Müvekkil Bilgilendirme").update(points=2)


class Migration(migrations.Migration):
    dependencies = [("office", "0022_officesettings_archive_folder_default_capacity")]

    operations = [migrations.RunPython(set_hearing_task_points, migrations.RunPython.noop)]
