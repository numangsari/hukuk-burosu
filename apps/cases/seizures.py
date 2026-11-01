"""İcra dosyalarında haciz takibi ve tarih geldiğinde görev oluşturma."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.text import tr_upper
from apps.office.models import TaskType
from apps.tasks.models import Task
from apps.tasks.services import on_created

from .models import Case, CaseStatus, CaseType, Seizure, SeizureRenewal


@transaction.atomic
def save_seizure(case, form, user):
    locked = Case.objects.select_for_update().get(pk=case.pk)
    if locked.case_type != CaseType.ENFORCEMENT or not locked.is_open:
        raise ValueError("Haciz takibi yalnızca açık icra dosyalarında değiştirilebilir.")
    if form.instance.pk:
        Seizure.objects.select_for_update().get(pk=form.instance.pk, case=locked)
    # Borçlu listesi kayıt anında da dosyanın güncel taraflarından doğrulanır.
    from .forms import SeizureForm

    form.instance.case = locked
    checked = SeizureForm(form.data, instance=form.instance)
    if not checked.is_valid():
        raise ValidationError(
            "Borçlu veya haciz bilgileri değişti. Sayfayı yenileyip tekrar deneyin."
        )
    item = checked.save(commit=False)
    item.case = locked
    if not item.pk:
        item.created_by = user
    item.full_clean()
    item.save()
    return item


@transaction.atomic
def _create_renewal(seizure_id, case_id, today):
    case = (
        Case.objects.select_for_update()
        .select_related("responsible_intern", "responsible_lawyer")
        .get(pk=case_id)
    )
    item = (
        Seizure.objects.select_for_update(of=("self",))
        .select_related("debtor_party", "debtor_client")
        .get(pk=seizure_id)
    )
    if (
        case.status != CaseStatus.OPEN
        or case.case_type != CaseType.ENFORCEMENT
        or not item.is_active
        or not item.renewal_on
        or not item.needs_renewal
        or item.renewal_on > today
        or item.renewals.filter(due_date=item.renewal_on).exists()
    ):
        return 0
    if not (case.responsible_intern.is_active and case.responsible_lawyer.is_active):
        return -1
    task_type, _ = TaskType.objects.get_or_create(name="Haciz yenileme")
    task = Task(
        case=case,
        title=tr_upper(f"HACZİ YENİLE: {item.debtor_display} — {item.asset_label}")[:300],
        task_type=task_type,
        assignee=case.responsible_intern,
        reviewer=case.responsible_lawyer,
        due_date=item.renewal_on,
        created_by=item.created_by,
        notes=f"Borçlu: {item.debtor_display}\nHaciz: {item.asset_label}\n"
        f"Durum: {item.state_label}\n"
        f"Haciz tarihi: {item.seized_on.strftime('%d.%m.%Y') if item.seized_on else '—'}\n"
        f"Yenileme tarihi: {item.renewal_on:%d.%m.%Y}\n{item.notes}",
    )
    task.full_clean()
    task.save()
    on_created(task, item.created_by)
    SeizureRenewal.objects.create(seizure=item, due_date=item.renewal_on, task=task)
    return 1


def create_due_tasks(today=None):
    today = today or timezone.localdate()
    candidates = Seizure.objects.filter(
        is_active=True,
        renewal_on__lte=today,
        case__status=CaseStatus.OPEN,
        case__case_type=CaseType.ENFORCEMENT,
    ).values_list("pk", "case_id")
    created = skipped = 0
    for seizure_id, case_id in candidates:
        # Liste alındıktan sonra dosya silinmiş olabilir.
        try:
            result = _create_renewal(seizure_id, case_id, today)
        except (Case.DoesNotExist, Seizure.DoesNotExist):
            continue
        created += result == 1
        skipped += result == -1
    return created, skipped
