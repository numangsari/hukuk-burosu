import datetime as dt

import pytest
from django.utils import timezone

from apps.cases.models import Hearing, HearingKind
from apps.tasks.models import Task
from apps.tasks.services import ensure_excuse_task

pytestmark = pytest.mark.django_db


def make(case, days, **kw):
    return Hearing.objects.create(
        case=case,
        kind=kw.pop("kind", HearingKind.HEARING),
        starts_at=timezone.now() + dt.timedelta(days=days),
        excuse_submitted=kw.pop("excuse_submitted", True),
        **kw,
    )


def test_excuse_creates_task_for_responsible_without_reviewer(case_factory, lawyer, admin_user):
    case = case_factory()
    hearing = make(case, 5, assigned_to=lawyer)
    task = ensure_excuse_task(hearing, admin_user)
    assert task.assignee == lawyer and task.reviewer is None
    assert task.case == case and task.hearing == hearing
    expected = timezone.localtime(hearing.starts_at).date() - dt.timedelta(days=1)
    assert task.due_date == expected
    assert "MAZERET" in task.title and "DURUŞMA" in task.title
    # Aynı duruşma için ikinci görev açılmaz.
    assert ensure_excuse_task(hearing, admin_user) is None
    assert Task.objects.filter(hearing=hearing).count() == 1


def test_excuse_due_date_never_in_past_and_admin_never_assignee(case_factory, admin_user):
    case = case_factory()
    hearing = make(case, 0, assigned_to=admin_user)  # sorumlu yönetici: dosya sorumlusuna düşer
    task = ensure_excuse_task(hearing, admin_user)
    assert task.due_date == timezone.localdate()
    assert task.assignee_id in {case.responsible_intern_id, case.responsible_lawyer_id}


def test_excuse_task_via_edit_view(admin_user, case_factory, lawyer):
    from django.test import Client as HttpClient
    from django.urls import reverse

    case = case_factory()
    hearing = make(case, 6, assigned_to=lawyer, excuse_submitted=False)
    c = HttpClient()
    c.force_login(admin_user)
    starts = (timezone.localtime() + dt.timedelta(days=6)).strftime("%Y-%m-%d %H:%M")
    r = c.post(
        reverse("hearings:edit", args=[hearing.pk]) + "?pencere=1",
        {
            "kind": "hearing",
            "case": case.pk,
            "assigned_to": lawyer.pk,
            "starts_at": starts,
            "attendance": "excuse",
        },
    )
    assert r.status_code == 200
    assert Task.objects.filter(hearing=hearing, assignee=lawyer).count() == 1
