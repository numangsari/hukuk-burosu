from django.db import migrations


def set_legacy_capacities(apps, schema_editor):
    Folder = apps.get_model("cases", "ArchiveFolder")
    Case = apps.get_model("cases", "Case")
    for folder in Folder.objects.filter(kind="legacy", capacity__isnull=True).iterator():
        values = list(
            Case.objects.filter(archive_folder_no__iexact=folder.name).values_list(
                "archive_no", flat=True
            )
        )
        numbers = [int(n) for n in values if n.isascii() and n.isdigit()]
        capacity = max([8, len(values), *numbers])
        if capacity <= 32767:
            folder.capacity = capacity
            folder.save(update_fields=["capacity"])


class Migration(migrations.Migration):
    dependencies = [("cases", "0037_archivefolder_types")]
    operations = [migrations.RunPython(set_legacy_capacities, migrations.RunPython.noop)]
