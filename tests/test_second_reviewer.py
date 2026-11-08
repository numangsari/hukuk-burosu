import datetime as dt

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.core.views import review_tasks_for
from apps.office.models import OfficeSettings, TaskType
from apps.tasks import services
from apps.tasks.models import Task, TaskPoint, TaskStatus

from .conftest import make_user

pytestmark = pytest.mark.django_db


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


@pytest.fixture
def second(db):
    return make_user("ikinci", "senior")


@pytest.fixture
def task(case_factory, intern, lawyer, second):
    return Task.objects.create(
        task_type=TaskType.objects.get(name="Müvekkil Görüşmesi"),
        title="Çift kontrollü görev",
        case=case_factory(),
        assignee=intern,
        reviewer=lawyer,
        second_reviewer=second,
        due_date=timezone.localdate() + dt.timedelta(days=3),
        created_by=lawyer,
    )


def keys(task, user):
    return {a.key for a in services.available_actions(task, user)}


def test_sequential_approval_flow(task, intern, lawyer, second):
    services.perform(task, "submit", intern)
    assert task.review_step == 1
    assert "approve" in keys(task, lawyer) and keys(task, second) == set()
    with pytest.raises(PermissionDenied):
        services.perform(task, "approve", second)

    services.perform(task, "approve", lawyer)
    task.refresh_from_db()
    assert task.status == TaskStatus.REVIEW and task.review_step == 2
    assert task.approval_seen and task.stage_label == "2. Kontrolde"
    assert keys(task, lawyer) == set() and {"approve", "revise"} <= keys(task, second)

    services.perform(task, "approve", second)
    task.refresh_from_db()
    assert task.status == TaskStatus.ACTIVE and not task.approval_seen
    assert task.stage_label == "Onaylandı"
    kinds = list(task.events.order_by("pk").values_list("kind", flat=True))
    assert kinds == ["submitted", "approved", "approved"]


def test_second_reviewer_revision_restarts_from_first(task, intern, lawyer, second):
    services.perform(task, "submit", intern)
    services.perform(task, "approve", lawyer)
    services.perform(task, "revise", second, "Eksik var")
    task.refresh_from_db()
    assert task.status == TaskStatus.ACTIVE and task.review_step == 1 and task.revision_requested
    services.perform(task, "submit", intern)
    assert keys(task, lawyer) >= {"approve"} and keys(task, second) == set()


def test_admin_cannot_act_on_review_steps(task, intern, admin_user):
    services.perform(task, "submit", intern)
    with pytest.raises(PermissionDenied):
        services.perform(task, "approve", admin_user)


def test_single_reviewer_task_is_unchanged(task, intern, lawyer):
    task.second_reviewer = None
    task.save()
    services.perform(task, "submit", intern)
    services.perform(task, "approve", lawyer)
    task.refresh_from_db()
    assert task.status == TaskStatus.ACTIVE and not task.approval_seen


def test_waiting_lists_follow_active_reviewer(task, intern, lawyer, second):
    services.perform(task, "submit", intern)
    assert list(review_tasks_for(lawyer)) == [task] and not review_tasks_for(second).exists()
    url = reverse("tasks:list") + "?sekme=bekleyen"
    assert "KONTROLLÜ GÖREV" in login(lawyer).get(url).content.decode().upper()
    services.perform(task, "approve", lawyer)
    assert not review_tasks_for(lawyer).exists() and list(review_tasks_for(second)) == [task]
    assert "KONTROLLÜ GÖREV" in login(second).get(url).content.decode().upper()
    assert "KONTROLLÜ GÖREV" not in login(lawyer).get(url).content.decode().upper()


def test_second_reviewer_sees_task_in_restricted_mode(task, second):
    office = OfficeSettings.load()
    office.case_visibility_mode = "restricted"
    office.save()
    other = make_user("baska", "lawyer")
    assert login(second).get(task.get_absolute_url()).status_code == 200
    assert login(other).get(task.get_absolute_url()).status_code == 404


def test_points_go_to_both_reviewers(task, intern, lawyer, second):
    office = OfficeSettings.load()
    office.use_task_points = True
    office.save()
    task.task_type.points = 3
    task.task_type.save()
    services.perform(task, "submit", intern)
    services.perform(task, "approve", lawyer)
    services.perform(task, "approve", second)
    services.perform(task, "close", intern, "Bitti")
    assert set(TaskPoint.objects.filter(task=task).values_list("user_id", flat=True)) == {
        intern.pk,
        lawyer.pk,
        second.pk,
    }


def form_data(task_type, intern, lawyer, second=None, **kw):
    data = {
        "task_type": task_type.pk,
        "title": "Yeni görev",
        "assignee": intern.pk,
        "reviewer": lawyer.pk,
        "due_date": "2026-11-20",
        "requires_accounting": "no",
    }
    if second:
        data["second_reviewer"] = second.pk
    data.update(kw)
    return data


def test_form_saves_second_reviewer(intern, lawyer, second):
    t = TaskType.objects.first()
    r = login(lawyer).post(reverse("tasks:create"), form_data(t, intern, lawyer, second))
    assert r.status_code == 302
    assert Task.objects.get().second_reviewer == second


def test_form_rejects_invalid_second_reviewer(intern, lawyer, second):
    t = TaskType.objects.first()
    c = login(lawyer)
    same_as_first = c.post(reverse("tasks:create"), form_data(t, intern, lawyer, lawyer))
    same_as_assignee = c.post(reverse("tasks:create"), form_data(t, intern, lawyer, intern))
    no_first = c.post(reverse("tasks:create"), form_data(t, intern, lawyer, second, reviewer=""))
    assert "second_reviewer" in same_as_first.context["form"].errors
    assert "second_reviewer" in same_as_assignee.context["form"].errors
    assert "second_reviewer" in no_first.context["form"].errors
    assert not Task.objects.exists()


def test_detail_shows_second_reviewer(task, lawyer):
    html = login(lawyer).get(task.get_absolute_url()).content.decode()
    assert "2. Kontrolcü" in html
