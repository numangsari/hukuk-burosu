"""Mevcut dosya konularını (dosya adlarını) büyük harfe çevirir."""

from django.db import migrations

from apps.core.text import tr_upper


def forwards(apps, schema_editor):
    Case = apps.get_model("cases", "Case")
    for pk, subject in Case.objects.values_list("pk", "subject").iterator():
        Case.objects.filter(pk=pk).update(subject=tr_upper(subject).strip())


class Migration(migrations.Migration):
    dependencies = [("cases", "0004_case_type_other")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
