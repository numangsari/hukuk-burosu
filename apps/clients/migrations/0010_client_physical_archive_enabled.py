from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0009_alter_client_responsible_intern"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="physical_archive_enabled",
            field=models.BooleanField(default=False, verbose_name="müvekkile özel fiziki klasör"),
        ),
    ]
