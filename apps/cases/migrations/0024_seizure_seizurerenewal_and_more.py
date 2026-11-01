# Haciz takibi ve bir kez oluşturulan yenileme görevleri.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cases', '0023_drop_archive_unique'),
        ('tasks', '0005_uppercase_task_titles'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Seizure',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='oluşturulma')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='güncellenme')),
                ('debtor', models.CharField(max_length=300, verbose_name='borçlu')),
                ('asset', models.CharField(max_length=500, verbose_name='haczedilen mal varlığı')),
                ('seized_on', models.DateField(verbose_name='haciz tarihi')),
                ('renewal_on', models.DateField(db_index=True, verbose_name='yenileme tarihi')),
                ('is_active', models.BooleanField(default=True, verbose_name='haciz takibi aktif')),
                ('notes', models.TextField(blank=True, verbose_name='not')),
                ('case', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seizures', to='cases.case')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_seizures', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'haciz takibi',
                'verbose_name_plural': 'haciz takipleri',
                'ordering': ['renewal_on', 'pk'],
            },
        ),
        migrations.CreateModel(
            name='SeizureRenewal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='oluşturulma')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='güncellenme')),
                ('due_date', models.DateField(verbose_name='yenileme tarihi')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='oluşturan')),
                ('seizure', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='renewals', to='cases.seizure')),
                ('task', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='seizure_renewal', to='tasks.task')),
            ],
            options={
                'verbose_name': 'haciz yenileme görevi',
                'verbose_name_plural': 'haciz yenileme görevleri',
            },
        ),
        migrations.AddConstraint(
            model_name='seizure',
            constraint=models.CheckConstraint(condition=models.Q(('renewal_on__gte', models.F('seized_on'))), name='seizure_renewal_after_date'),
        ),
        migrations.AddConstraint(
            model_name='seizurerenewal',
            constraint=models.UniqueConstraint(fields=('seizure', 'due_date'), name='unique_seizure_renewal'),
        ),
    ]
