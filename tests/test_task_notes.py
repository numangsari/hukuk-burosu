import datetime as dt

import pytest
from django.test import Client as HttpClient
from django.urls import reverse

from apps.office.models import TaskType
from apps.tasks.models import Task, TaskEvent
from apps.tasks.services import LEDGER_NOTE_PREFIX

pytestmark = pytest.mark.django_db


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def make_task(case):
    return Task.objects.create(
        task_type=TaskType.objects.first(),
        title="x",
        case=case,
        assignee=case.responsible_intern,
        reviewer=case.responsible_lawyer,
        due_date=dt.date(2026, 11, 5),
    )


def test_task_note_delete_rights(lawyer, intern, admin_user, case_factory):
    case = case_factory()
    task = make_task(case)
    mine = TaskEvent.objects.create(
        task=task, actor=intern, kind=TaskEvent.Kind.NOTE, comment="benim notum"
    )
    url = reverse("tasks:note_delete", args=[task.pk, mine.pk])
    # Başkası silemez.
    assert login(lawyer).post(url).status_code == 403
    assert TaskEvent.objects.filter(pk=mine.pk).exists()
    # Yazan siler.
    assert login(intern).post(url).status_code == 302
    assert not TaskEvent.objects.filter(pk=mine.pk).exists()
    # Yönetici de silebilir.
    other = TaskEvent.objects.create(
        task=task, actor=intern, kind=TaskEvent.Kind.NOTE, comment="başka"
    )
    login(admin_user).post(reverse("tasks:note_delete", args=[task.pk, other.pk]))
    assert not TaskEvent.objects.filter(pk=other.pk).exists()


def test_system_ledger_note_cannot_be_deleted(intern, case_factory):
    task = make_task(case_factory())
    auto = TaskEvent.objects.create(
        task=task, actor=intern, kind=TaskEvent.Kind.NOTE, comment=f"{LEDGER_NOTE_PREFIX} 1 — x"
    )
    r = login(intern).post(reverse("tasks:note_delete", args=[task.pk, auto.pk]))
    assert r.status_code == 403
    assert TaskEvent.objects.filter(pk=auto.pk).exists()
