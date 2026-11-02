# Django 5.2.18 tarafından oluşturuldu.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0007_retainer_agreement'),
    ]

    operations = [
        migrations.AlterField(
            model_name='client',
            name='poa_no',
            field=models.PositiveIntegerField(blank=True, help_text='Fiziki vekalet klasöründeki sıra numarası (V-121 için 121). Aynı vekaleti paylaşan müvekkillerde numara aynı olabilir.', null=True, verbose_name='vekalet no'),
        ),
    ]
