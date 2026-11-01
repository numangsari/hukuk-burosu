# Tür bazlı haciz takibi; önceki borçlu ve mal varlığı bilgileri korunur.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cases', '0024_seizure_seizurerenewal_and_more'),
        ('clients', '0007_retainer_agreement'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='seizure',
            name='address',
            field=models.TextField(blank=True, verbose_name='adres'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='bank_name',
            field=models.CharField(blank=True, max_length=200, verbose_name='banka adı'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='debtor_client',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='debtor_seizures', to='clients.client'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='debtor_party',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='seizures', to='clients.party'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='employer',
            field=models.CharField(blank=True, max_length=200, verbose_name='işveren / işyeri'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='kind',
            field=models.CharField(blank=True, choices=[('salary', 'Maaş Haczi'), ('bank', 'Banka Hesabı'), ('vehicle', 'Araç Haczi'), ('property', 'Tapu Haczi'), ('location', 'Mahal Haczi'), ('notice', '89/1-2-3 Haczi'), ('claim', 'Alacaklı Olduğu İcra Dosyası Haczi')], max_length=20, verbose_name='haciz türü'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='notice_stage',
            field=models.CharField(blank=True, choices=[('89/1', '89/1'), ('89/2', '89/2'), ('89/3', '89/3')], max_length=4, verbose_name='ihbarname'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='plate',
            field=models.CharField(blank=True, max_length=20, verbose_name='plaka'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='property_info',
            field=models.CharField(blank=True, max_length=500, verbose_name='taşınmaz bilgisi'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='recipient',
            field=models.CharField(blank=True, max_length=300, verbose_name='ihbarname muhatabı'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='related_case_info',
            field=models.CharField(blank=True, max_length=300, verbose_name='alacaklı olduğu dosya bilgisi'),
        ),
        migrations.AddField(
            model_name='seizure',
            name='state',
            field=models.CharField(blank=True, max_length=32, verbose_name='durum'),
        ),
        migrations.AlterField(
            model_name='seizure',
            name='asset',
            field=models.CharField(blank=True, max_length=500, verbose_name='önceki mal varlığı bilgisi'),
        ),
        migrations.AlterField(
            model_name='seizure',
            name='renewal_on',
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name='yenileme tarihi'),
        ),
        migrations.AlterField(
            model_name='seizure',
            name='seized_on',
            field=models.DateField(blank=True, null=True, verbose_name='haciz tarihi'),
        ),
        migrations.AddConstraint(
            model_name='seizure',
            constraint=models.CheckConstraint(condition=models.Q(('debtor_party__isnull', True), ('debtor_client__isnull', True), _connector='OR'), name='seizure_single_debtor'),
        ),
    ]
