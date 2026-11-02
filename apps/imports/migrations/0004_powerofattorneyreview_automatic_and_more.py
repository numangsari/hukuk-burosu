# Django 5.2.18 tarafından oluşturuldu.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0003_powerofattorneyreview_source_note_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='powerofattorneyreview',
            name='automatic',
            field=models.BooleanField(default=False, verbose_name='otomatik öneriyle aktarıldı'),
        ),
        migrations.AlterField(
            model_name='powerofattorneyreview',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
    ]
