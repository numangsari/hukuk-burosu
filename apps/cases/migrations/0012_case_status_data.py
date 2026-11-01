from django.db import migrations

JUDICIAL = {"civil", "criminal", "administrative"}
DEFAULT_STAGE = {
    "enforcement": "started",
    "investigation": "complaint",
    "consultancy": "draft",
    "mediation": "applied",
    "notice": "draft",
    "other": "preparation",
}
FINALIZED_TYPES = JUDICIAL | {"enforcement"}


def to_new_model(apps, schema_editor):
    """Eski durum (Derdest/Karar/Kesinleşti/Kapandı) ve aşamayı açık/kapalı modeline taşır."""
    Case = apps.get_model("cases", "Case")
    for case in Case.objects.all().iterator():
        judicial = case.case_type in JUDICIAL
        default = "pending" if judicial else DEFAULT_STAGE.get(case.case_type, "preparation")
        if case.status == "closed":
            case.status = "closed"
            case.stage = default
            case.closing_reason = "other"
            case.closing_note = "Önceki sistemde yalnızca 'Kapandı' olarak kayıtlıydı."
        else:
            stage = default
            if case.status == "decided" and judicial:
                stage = "decided"
            elif case.status == "finalized" and case.case_type in FINALIZED_TYPES:
                stage = "finalized"
            elif judicial and case.stage in ("appeal", "cassation"):
                stage = case.stage
            case.status = "open"
            case.stage = stage
        case.save(update_fields=["status", "stage", "closing_reason", "closing_note"])


class Migration(migrations.Migration):
    dependencies = [("cases", "0011_case_status_stage_closing")]

    operations = [migrations.RunPython(to_new_model, migrations.RunPython.noop)]
