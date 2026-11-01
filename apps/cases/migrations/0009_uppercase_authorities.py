from django.db import migrations


def uppercase_authorities(apps, schema_editor):
    Case = apps.get_model("cases", "Case")
    for case in Case.objects.using(schema_editor.connection.alias).exclude(authority="").iterator():
        authority = case.authority.translate(str.maketrans({"i": "İ", "ı": "I"})).upper().strip()
        if authority != case.authority:
            Case.objects.using(schema_editor.connection.alias).filter(pk=case.pk).update(authority=authority)


class Migration(migrations.Migration):
    dependencies = [("cases", "0008_case_client_role_alter_caseparty_role")]
    operations = [migrations.RunPython(uppercase_authorities, migrations.RunPython.noop)]
