from django.db import migrations


def create_default_categories(apps, schema_editor):
    Category = apps.get_model("cases", "ArchiveCategory")
    Folder = apps.get_model("cases", "ArchiveFolder")
    Settings = apps.get_model("office", "OfficeSettings")
    settings = Settings.objects.first()
    capacity = settings.archive_folder_default_capacity if settings else 8
    names = (
        "Dava",
        "İcra",
        "İhtarname",
        "Arabuluculuk",
        "Sözleşme",
        "Vekaletname",
        "Avukatlık Ücret Sözleşmesi",
        "Soruşturma",
        "Satış Memurluğu",
        "Diğer",
    )
    for name in names:
        category, _ = Category.objects.get_or_create(name=name)
        for state, label in (("open", "Açık"), ("closed", "Kapalı")):
            full_name = f"{label} {name} 1"
            if not Folder.objects.filter(name__iexact=full_name).exists():
                Folder.objects.create(
                    name=full_name,
                    kind="category",
                    category=category,
                    physical_state=state,
                    number=1,
                    capacity=capacity,
                )


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0039_archivefolder_number_archivefolder_physical_state_and_more"),
        ("office", "0022_officesettings_archive_folder_default_capacity"),
    ]
    operations = [migrations.RunPython(create_default_categories, migrations.RunPython.noop)]
