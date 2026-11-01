"""Mevcut müvekkil adlarını büyük harfe çevirir (yeni kayıtlar save() içinde çevrilir)."""

from django.db import migrations

from apps.core.text import fold, tr_upper


def forwards(apps, schema_editor):
    Client = apps.get_model("clients", "Client")
    for c in Client.objects.all().iterator():
        first, last, title = tr_upper(c.first_name), tr_upper(c.last_name), tr_upper(c.title)
        name = f"{first} {last}".strip() if c.kind == "person" else title.strip()
        Client.objects.filter(pk=c.pk).update(
            first_name=first, last_name=last, title=title, name=name, search_key=fold(name)
        )


class Migration(migrations.Migration):
    dependencies = [("clients", "0005_remove_client_is_active_client_poa_no")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
