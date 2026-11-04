from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0042_archivecategory_client_alter_archivecategory_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="archivefolder",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="yeni yerleşime açık"),
        ),
    ]
