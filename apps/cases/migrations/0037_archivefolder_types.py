from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cases", "0036_alter_case_client_role_alter_caseparty_role_and_more")]

    operations = [
        migrations.AddField(
            model_name="archivefolder",
            name="custom_kind",
            field=models.CharField(blank=True, max_length=30, verbose_name="diğer tür adı"),
        ),
        migrations.AlterField(
            model_name="archivefolder",
            name="kind",
            field=models.CharField(
                choices=[
                    ("open", "Açık"),
                    ("closed", "Kapalı"),
                    ("enforcement", "İcra"),
                    ("proxy", "Vekaletnameler"),
                    ("notice", "İhtarnameler"),
                    ("mediation", "Arabuluculuklar"),
                    ("contract", "Sözleşmeler"),
                    ("fee_contract", "Avukatlık Ücret Sözleşmeleri"),
                    ("other", "Diğer"),
                    ("legacy", "Eski kayıt"),
                ],
                max_length=12,
                verbose_name="tür",
            ),
        ),
    ]
