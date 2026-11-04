import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0041_optional_archive_states"),
        ("clients", "0010_client_physical_archive_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="archivecategory",
            name="client",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="physical_archive_category",
                to="clients.client",
                verbose_name="özel müvekkil",
            ),
        ),
        migrations.AlterField(
            model_name="archivecategory",
            name="name",
            field=models.CharField(max_length=320, unique=True, verbose_name="tür adı"),
        ),
        migrations.AlterField(
            model_name="archivefolder",
            name="name",
            field=models.CharField(max_length=340, unique=True, verbose_name="klasör adı"),
        ),
        migrations.AlterField(
            model_name="case",
            name="archive_folder_no",
            field=models.CharField(blank=True, max_length=340, verbose_name="klasör no"),
        ),
    ]
