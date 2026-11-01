# Tahsilatları oluşturan kapanış kaydıyla ilişkilendir.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0002_remove_offset_kind'),
        ('cases', '0023_drop_archive_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='ledgerentry',
            name='closing_event',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='collections', to='cases.caseevent', verbose_name='kapanış kaydı'),
        ),
    ]
