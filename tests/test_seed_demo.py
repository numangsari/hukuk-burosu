import pytest
from django.core.management import call_command

from apps.cases.models import Case
from apps.clients.models import Client
from apps.tasks.models import Task, TaskPoint


@pytest.mark.django_db
def test_seed_demo_uses_current_types_and_archive_format(settings, lawyer, intern):
    settings.DEBUG = True
    call_command("seed_demo")
    assert Client.objects.filter(notes__contains="seed_demo").count() == 18
    assert Case.objects.filter(archive_folder_no="1", archive_no="58", status="closed").exists()
    assert Case.objects.filter(
        archive_folder_no="15", archive_no="8", case_type="enforcement"
    ).exists()
    assert Case.objects.get(archive_folder_no="15", archive_no="8").seizures.count() == 2
    assert Case.objects.filter(archive_folder_no="4", archive_no="85").exists()
    assert not Task.objects.filter(task_type__is_active=False).exists()
    assert Task.objects.filter(status="review").exists()
    assert Task.objects.filter(status="active", approval_seen=False).exists()
    assert Task.objects.filter(status="done").count() == 5
    assert TaskPoint.objects.count() == 10
    assert not Task.objects.filter(case__client_role="").exists()
    call_command("seed_demo")
    assert Client.objects.filter(notes__contains="seed_demo").count() == 18
