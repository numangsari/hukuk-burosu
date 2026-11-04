import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0038_legacy_folder_capacities"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="archivefolder",
            name="number",
            field=models.PositiveIntegerField(
                blank=True, null=True, verbose_name="klasör numarası"
            ),
        ),
        migrations.AddField(
            model_name="archivefolder",
            name="physical_state",
            field=models.CharField(
                blank=True,
                choices=[("open", "Açık"), ("closed", "Kapalı")],
                max_length=6,
                verbose_name="fiziki durum",
            ),
        ),
        migrations.AddField(
            model_name="case",
            name="archive_needs_review",
            field=models.BooleanField(default=False, verbose_name="fiziki arşiv yeri incelenecek"),
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
                    ("category", "Türlü klasör"),
                    ("legacy", "Eski kayıt"),
                ],
                max_length=12,
                verbose_name="tür",
            ),
        ),
        migrations.CreateModel(
            name="ArchiveCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="oluşturulma")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="güncellenme")),
                ("name", models.CharField(max_length=40, unique=True, verbose_name="tür adı")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="oluşturan",
                    ),
                ),
            ],
            options={
                "verbose_name": "fiziki klasör türü",
                "verbose_name_plural": "fiziki klasör türleri",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="archivefolder",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="folders",
                to="cases.archivecategory",
                verbose_name="tür",
            ),
        ),
        migrations.AddConstraint(
            model_name="archivefolder",
            constraint=models.UniqueConstraint(
                fields=("category", "physical_state", "number"),
                name="archive_category_state_number_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="archivecategory",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="archive_category_name_ci_unique",
            ),
        ),
    ]
