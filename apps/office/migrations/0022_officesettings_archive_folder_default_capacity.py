from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("office", "0021_officesettings_google_color_discovery_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="officesettings",
            name="archive_folder_default_capacity",
            field=models.PositiveSmallIntegerField(
                default=8,
                help_text="Yeni klasörlerde önerilen dosya sayısı; klasör oluşturulurken değiştirilebilir.",
                verbose_name="varsayılan fiziki klasör kapasitesi",
            ),
        ),
    ]
