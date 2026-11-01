import django.db.models.deletion
from django.db import migrations, models


def copy_co_clients(apps, schema_editor):
    """Ek müvekkillere, dosyadaki asıl müvekkilin sıfatı varsayılan olarak verilir."""
    Case = apps.get_model("cases", "Case")
    Link = apps.get_model("cases", "CaseCoClient")
    old = Case.co_clients.through
    for row in old.objects.all():
        role = Case.objects.filter(pk=row.case_id).values_list("client_role", flat=True).first()
        Link.objects.get_or_create(case_id=row.case_id, client_id=row.client_id, defaults={"role": role or ""})


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0007_retainer_agreement"),
        ("cases", "0021_co_clients"),
    ]

    operations = [
        migrations.CreateModel(
            name="CaseCoClient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(blank=True, max_length=32, verbose_name="müvekkilin sıfatı")),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="co_client_links", to="cases.case")),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="co_case_links", to="clients.client")),
            ],
            options={
                "verbose_name": "dosya müvekkili",
                "verbose_name_plural": "dosya müvekkilleri",
                "ordering": ["pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="casecoclient",
            constraint=models.UniqueConstraint(fields=("case", "client"), name="unique_case_co_client"),
        ),
        migrations.RunPython(copy_co_clients, migrations.RunPython.noop),
        migrations.RemoveField(model_name="case", name="co_clients"),
        migrations.AddField(
            model_name="case",
            name="co_clients",
            field=models.ManyToManyField(
                blank=True,
                related_name="co_cases",
                through="cases.CaseCoClient",
                to="clients.client",
                verbose_name="ek müvekkiller",
            ),
        ),
    ]
