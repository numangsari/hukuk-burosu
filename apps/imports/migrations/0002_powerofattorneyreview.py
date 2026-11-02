# Django 5.2.18 tarafından oluşturuldu.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0007_retainer_agreement'),
        ('imports', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PowerOfAttorneyReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_sha256', models.CharField(max_length=64)),
                ('source_row', models.PositiveIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('client', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='imported_poa_rows', to='clients.client')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'vekalet listesi incelemesi',
                'verbose_name_plural': 'vekalet listesi incelemeleri',
                'constraints': [models.UniqueConstraint(fields=('source_sha256', 'source_row'), name='unique_poa_review_source_row')],
            },
        ),
    ]
