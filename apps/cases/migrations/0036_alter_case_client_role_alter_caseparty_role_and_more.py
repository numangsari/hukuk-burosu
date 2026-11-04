import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


def copy_existing_folders(apps, schema_editor):
    Case = apps.get_model("cases", "Case")
    ArchiveFolder = apps.get_model("cases", "ArchiveFolder")
    names = (
        Case.objects.exclude(archive_folder_no="")
        .values_list("archive_folder_no", flat=True)
        .distinct()
    )
    for name in names.iterator():
        if name.strip() and not ArchiveFolder.objects.filter(name__iexact=name).exists():
            ArchiveFolder.objects.create(name=name, kind="legacy", capacity=None)


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0035_alter_hearing_options_hearing_assigned_to_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ArchiveFolder",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="oluşturulma")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="güncellenme")),
                ("name", models.CharField(max_length=50, unique=True, verbose_name="klasör adı")),
                (
                    "kind",
                    models.CharField(
                        choices=[("open", "Açık"), ("closed", "Kapalı"), ("legacy", "Eski kayıt")],
                        max_length=10,
                        verbose_name="tür",
                    ),
                ),
                (
                    "capacity",
                    models.PositiveSmallIntegerField(
                        blank=True, null=True, verbose_name="kapasite"
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="oluşturan",
                    ),
                ),
            ],
            options={
                "verbose_name": "fiziki klasör",
                "verbose_name_plural": "fiziki klasörler",
                "ordering": ["name"],
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        name="archive_folder_name_ci_unique",
                    )
                ],
            },
        ),
        migrations.RunPython(copy_existing_folders, migrations.RunPython.noop),
    ]
