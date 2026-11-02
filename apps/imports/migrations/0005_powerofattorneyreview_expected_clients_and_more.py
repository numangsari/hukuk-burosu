# Django 5.2.18 tarafından oluşturuldu.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0008_alter_client_poa_no'),
        ('imports', '0004_powerofattorneyreview_automatic_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='powerofattorneyreview',
            name='expected_clients',
            field=models.PositiveIntegerField(default=1, verbose_name='satırdaki müvekkil sayısı'),
        ),
        migrations.CreateModel(
            name='PowerOfAttorneyReviewMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('client', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='imported_poa_members', to='clients.client')),
                ('review', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='members', to='imports.powerofattorneyreview')),
            ],
            options={
                'verbose_name': 'vekalet listesi ek müvekkili',
                'verbose_name_plural': 'vekalet listesi ek müvekkilleri',
                'constraints': [models.UniqueConstraint(fields=('review', 'client'), name='unique_poa_review_member')],
            },
        ),
    ]
