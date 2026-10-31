from django.db import migrations


def forwards(apps, schema_editor):
    TaskType = apps.get_model("office", "TaskType")
    TaskType.objects.filter(name__in=["Dilekçe", "Bilirkişi"]).update(requires_document=True)


class Migration(migrations.Migration):
    dependencies = [("office", "0004_officesettings_documents_root_and_more")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
