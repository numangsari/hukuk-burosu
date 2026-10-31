# Django 5.2.18 ile 31 Ekim 2026 tarihinde oluşturuldu.

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='BackupRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('kind', models.CharField(choices=[('scheduled', 'Zamanlanmış'), ('manual', 'Elle'), ('update', 'Güncelleme öncesi')], default='scheduled', max_length=20)),
                ('status', models.CharField(choices=[('ok', 'Başarılı'), ('error', 'Hatalı')], default='error', max_length=10)),
                ('file_name', models.CharField(blank=True, max_length=200)),
                ('size', models.PositiveBigIntegerField(default=0)),
                ('copied_to', models.CharField(blank=True, max_length=500)),
                ('message', models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'yedek',
                'verbose_name_plural': 'yedekler',
                'ordering': ['-started_at'],
            },
        ),
    ]
