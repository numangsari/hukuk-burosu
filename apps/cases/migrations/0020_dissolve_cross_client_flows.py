from django.db import migrations


def dissolve(apps, schema_editor):
    """Yalnızca aynı müvekkilin dosyaları bağlanabilir; farklı müvekkillerin dosyalarını
    içeren eski ortak safahat grupları dağıtılır (dosyalar silinmez)."""
    Case = apps.get_model("cases", "Case")
    flow_ids = set(Case.objects.exclude(flow_id=None).values_list("flow_id", flat=True))
    for flow_id in flow_ids:
        clients = set(Case.objects.filter(flow_id=flow_id).values_list("client_id", flat=True))
        if len(clients) > 1:
            Case.objects.filter(flow_id=flow_id).update(flow=None, flow_position=0, flow_note="")


class Migration(migrations.Migration):
    dependencies = [("cases", "0019_flow_as_files")]

    operations = [migrations.RunPython(dissolve, migrations.RunPython.noop)]
