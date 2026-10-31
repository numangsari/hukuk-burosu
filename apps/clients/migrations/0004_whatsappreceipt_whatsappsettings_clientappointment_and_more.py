# WhatsApp mesajları ve müvekkil randevuları için oluşturuldu.

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cases', '0004_case_type_other'),
        ('clients', '0003_folder_help'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WhatsAppReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_id', models.CharField(max_length=200, unique=True)),
                ('status', models.CharField(max_length=12)),
                ('occurred_at', models.DateTimeField()),
                ('error_code', models.CharField(blank=True, max_length=30)),
            ],
            options={
                'verbose_name': 'WhatsApp teslim bilgisi',
                'verbose_name_plural': 'WhatsApp teslim bilgileri',
            },
        ),
        migrations.CreateModel(
            name='WhatsAppSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=False, verbose_name='WhatsApp gönderimini aç')),
                ('reminder_hours', models.PositiveSmallIntegerField(default=24, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(168)], verbose_name='kaç saat önce hatırlatılsın')),
                ('language', models.CharField(default='tr', max_length=10, verbose_name='hazır mesaj dili')),
                ('hearing_template', models.CharField(blank=True, max_length=120, verbose_name='onaylı duruşma mesajının adı')),
                ('appointment_template', models.CharField(blank=True, max_length=120, verbose_name='onaylı randevu mesajının adı')),
                ('start_template', models.CharField(blank=True, max_length=120, verbose_name='onaylı sohbet başlatma mesajının adı')),
                ('webhook_verified_at', models.DateTimeField(blank=True, editable=False, null=True)),
            ],
            options={
                'verbose_name': 'WhatsApp ofis ayarı',
                'verbose_name_plural': 'WhatsApp ofis ayarı',
            },
        ),
        migrations.CreateModel(
            name='ClientAppointment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='oluşturulma')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='güncellenme')),
                ('title', models.CharField(max_length=200, verbose_name='randevu konusu')),
                ('starts_at', models.DateTimeField(verbose_name='tarih ve saat')),
                ('location', models.CharField(blank=True, max_length=200, verbose_name='yer')),
                ('status', models.CharField(choices=[('planned', 'Planlandı'), ('done', 'Yapıldı'), ('cancelled', 'İptal edildi')], default='planned', max_length=20, verbose_name='durum')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='appointments', to='clients.client')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='oluşturan')),
            ],
            options={
                'verbose_name': 'müvekkil randevusu',
                'verbose_name_plural': 'müvekkil randevuları',
                'ordering': ['-starts_at', '-pk'],
            },
        ),
        migrations.CreateModel(
            name='WhatsAppContact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='oluşturulma')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='güncellenme')),
                ('phone_number', models.CharField(max_length=15, unique=True, validators=[django.core.validators.RegexValidator('^[1-9][0-9]{7,14}$', 'Geçerli bir uluslararası numara seçin.')], verbose_name='WhatsApp numarası')),
                ('opted_in', models.BooleanField(default=False, verbose_name='müvekkil WhatsApp mesajlarını kabul etti')),
                ('reminders_enabled', models.BooleanField(default=False, verbose_name='duruşma ve randevu hatırlatması gönder')),
                ('consent_recorded_at', models.DateTimeField(blank=True, null=True)),
                ('client', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='whatsapp_contact', to='clients.client')),
                ('consent_recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('contact', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='clients.clientcontact')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='oluşturan')),
            ],
            options={
                'verbose_name': 'müvekkil WhatsApp tercihi',
                'verbose_name_plural': 'müvekkil WhatsApp tercihleri',
            },
        ),
        migrations.CreateModel(
            name='WhatsAppMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone_number', models.CharField(db_index=True, max_length=15)),
                ('direction', models.CharField(choices=[('incoming', 'Gelen'), ('outgoing', 'Giden')], max_length=10)),
                ('status', models.CharField(choices=[('received', 'Alındı'), ('queued', 'Gönderilmeyi bekliyor'), ('sending', 'Gönderiliyor'), ('sent', "WhatsApp'a iletildi"), ('delivered', 'Ulaştı'), ('read', 'Okundu'), ('failed', 'Gönderilemedi'), ('uncertain', 'Gönderim sonucu kontrol edilmeli'), ('cancelled', 'Gönderimden kaldırıldı')], max_length=12)),
                ('body', models.TextField(blank=True, max_length=4096, verbose_name='mesaj')),
                ('message_type', models.CharField(default='text', max_length=20)),
                ('external_id', models.CharField(blank=True, max_length=200)),
                ('template_name', models.CharField(blank=True, max_length=120)),
                ('template_parameters', models.JSONField(blank=True, default=list)),
                ('dedup_key', models.CharField(blank=True, max_length=200)),
                ('occurred_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('attempted_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('error', models.CharField(blank=True, max_length=300)),
                ('appointment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='clients.clientappointment')),
                ('client', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='whatsapp_messages', to='clients.client')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('hearing', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='cases.hearing')),
            ],
            options={
                'verbose_name': 'WhatsApp mesajı',
                'verbose_name_plural': 'WhatsApp mesajları',
                'ordering': ['-occurred_at', '-pk'],
                'indexes': [models.Index(fields=['phone_number', 'direction', 'occurred_at'], name='clients_wha_phone_n_5b5f89_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('external_id', ''), _negated=True), fields=('external_id',), name='unique_whatsapp_message'), models.UniqueConstraint(condition=models.Q(('dedup_key', ''), _negated=True), fields=('dedup_key',), name='unique_whatsapp_dispatch')],
            },
        ),
    ]
