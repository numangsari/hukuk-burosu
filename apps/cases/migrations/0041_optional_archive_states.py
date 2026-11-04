from django.db import migrations, models


def adjust_default_categories(apps, schema_editor):
    Category = apps.get_model("cases", "ArchiveCategory")
    Folder = apps.get_model("cases", "ArchiveFolder")
    Case = apps.get_model("cases", "Case")
    for name in ("İhtarname", "Arabuluculuk"):
        category = Category.objects.filter(name=name).first()
        if not category:
            continue
        category.tracks_state = False
        category.save(update_fields=["tracks_state"])
        folders = Folder.objects.filter(
            category=category, number=1, physical_state__in=["open", "closed"]
        )
        capacity = 8
        for folder in folders:
            capacity = folder.capacity or capacity
            if Case.objects.filter(archive_folder_no__iexact=folder.name).exists():
                folder.category = None
                folder.number = None
                folder.physical_state = ""
                folder.kind = "legacy"
                folder.save(update_fields=["category", "number", "physical_state", "kind"])
            else:
                folder.delete()
        full_name = f"{name} 1"
        if not Folder.objects.filter(name__iexact=full_name).exists():
            Folder.objects.create(
                name=full_name,
                kind="category",
                category=category,
                physical_state="single",
                number=1,
                capacity=capacity,
            )


class Migration(migrations.Migration):
    dependencies = [("cases", "0040_archive_default_categories")]
    operations = [
        migrations.AddField(
            model_name="archivecategory",
            name="tracks_state",
            field=models.BooleanField(default=True, verbose_name="açık / kapalı ayrımı"),
        ),
        migrations.AlterField(
            model_name="archivefolder",
            name="physical_state",
            field=models.CharField(
                blank=True,
                choices=[("open", "Açık"), ("closed", "Kapalı"), ("single", "Ayrımsız")],
                max_length=6,
                verbose_name="fiziki durum",
            ),
        ),
        migrations.RunPython(adjust_default_categories, migrations.RunPython.noop),
    ]
