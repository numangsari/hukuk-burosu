# Django 5.2.18 tarafından oluşturuldu.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0002_powerofattorneyreview'),
    ]

    operations = [
        migrations.AddField(
            model_name='powerofattorneyreview',
            name='source_note',
            field=models.TextField(blank=True, verbose_name='kaynak notu'),
        ),
        migrations.AddField(
            model_name='powerofattorneyreview',
            name='source_reference',
            field=models.TextField(blank=True, verbose_name='kaynak vekalet numarası'),
        ),
    ]
