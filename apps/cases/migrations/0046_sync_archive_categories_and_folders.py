from django.db import migrations


def populate_archive_data(apps, schema_editor):
    ArchiveCategory = apps.get_model("cases", "ArchiveCategory")
    ArchiveFolder = apps.get_model("cases", "ArchiveFolder")
    Case = apps.get_model("cases", "Case")

    # 1. Varsayılan dava türlerini kategorilere bağla (Configurable / Dinamik)
    category_case_types = {
        "Dava": ["civil", "criminal", "administrative"],
        "İcra": ["enforcement"],
        "İhtarname": ["notice"],
        "Arabuluculuk": ["mediation"],
        "Sözleşme": ["consultancy"],
        "Soruşturma": ["investigation"],
        "Satış Memurluğu": ["sales_office"],
        "Diğer": ["other"],
    }

    for cat_name, types in category_case_types.items():
        category = ArchiveCategory.objects.filter(name__iexact=cat_name, client__isnull=True).first()
        if category:
            category.default_for_case_types = types
            category.save(update_fields=["default_for_case_types"])

    # 2. Case kayıtlarının archive_folder_id alanını doldur
    folder_map = {f.name.casefold(): f.id for f in ArchiveFolder.objects.all()}
    
    updated_cases = []
    for case in Case.objects.exclude(archive_folder_no="").filter(archive_folder__isnull=True).only("id", "archive_folder_no"):
        folder_id = folder_map.get(case.archive_folder_no.casefold())
        if folder_id:
            case.archive_folder_id = folder_id
            updated_cases.append(case)
            if len(updated_cases) >= 1000:
                Case.objects.bulk_update(updated_cases, ["archive_folder_id"])
                updated_cases = []
                
    if updated_cases:
        Case.objects.bulk_update(updated_cases, ["archive_folder_id"])


def reverse_populate(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("cases", "0045_archivecategory_default_for_case_types_and_more"),
    ]

    operations = [
        migrations.RunPython(populate_archive_data, reverse_populate),
    ]
