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
    services.perform(task, "submit", intern, "Not")
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


def test_first_reviewer_revision_returns_to_assignee_then_first_again(task, intern, lawyer, second):
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "revise", lawyer, "Düzelt")
    task.refresh_from_db()
    assert task.status == TaskStatus.ACTIVE and task.review_step == 1
    services.perform(task, "submit", intern, "Düzeltildi")
    task.refresh_from_db()
    assert task.review_step == 1 and keys(task, lawyer) >= {"approve"}


def test_second_reviewer_revision_goes_back_and_resubmit_skips_first(task, intern, lawyer, second):
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    services.perform(task, "revise", second, "Eksik var")
    task.refresh_from_db()
    assert task.status == TaskStatus.ACTIVE and task.review_step == 2 and task.revision_requested
    services.perform(task, "submit", intern, "Eksik giderildi")
    task.refresh_from_db()
    # Sorumlu yeniden gönderince doğrudan 2. kontrolcüye gider.
    assert task.status == TaskStatus.REVIEW and task.review_step == 2
    assert keys(task, second) >= {"approve"} and keys(task, lawyer) == set()


def test_second_reviewer_approval_returns_to_assignee_to_close(task, intern, lawyer, second):
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    services.perform(task, "approve", second)
    task.refresh_from_db()
    assert task.status == TaskStatus.ACTIVE and not task.approval_seen
    assert "close" in keys(task, intern)


def test_team_stages_show_who_holds_the_task(task, intern, lawyer, second):
    def states():
        return {s["key"]: s["state"] for s in task.team_stages}

    assert states() == {"assignee": "current", "reviewer": "waiting", "second": "waiting"}
    services.perform(task, "submit", intern, "Not")
    assert states() == {"assignee": "done", "reviewer": "current", "second": "waiting"}
    services.perform(task, "approve", lawyer)
    assert states() == {"assignee": "done", "reviewer": "done", "second": "current"}
    services.perform(task, "revise", second, "Eksik")
    assert states() == {"assignee": "current", "reviewer": "done", "second": "waiting"}


def test_admin_cannot_act_on_review_steps(task, intern, admin_user):
    services.perform(task, "submit", intern, "Not")
    with pytest.raises(PermissionDenied):
        services.perform(task, "approve", admin_user)


def test_single_reviewer_task_is_unchanged(task, intern, lawyer):
    task.second_reviewer = None
    task.save()
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    task.refresh_from_db()
    assert task.status == TaskStatus.ACTIVE and not task.approval_seen


def test_waiting_lists_follow_active_reviewer(task, intern, lawyer, second):
    services.perform(task, "submit", intern, "Not")
    assert list(review_tasks_for(lawyer)) == [task] and not review_tasks_for(second).exists()
    url = reverse("tasks:list") + "?sekme=bekleyen"
    assert "KONTROLLÜ GÖREV" in login(lawyer).get(url).content.decode().upper()
    services.perform(task, "approve", lawyer)
    assert not review_tasks_for(lawyer).exists() and list(review_tasks_for(second)) == [task]
    assert "KONTROLLÜ GÖREV" in login(second).get(url).content.decode().upper()
    assert "KONTROLLÜ GÖREV" not in login(lawyer).get(url).content.decode().upper()


def test_second_reviewer_sees_task_in_restricted_mode(task, second):
    office = OfficeSettings.load()
    office.role_permissions = {"cases.view_all": ["admin", "senior", "secretary", "accountant"]}
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
    services.perform(task, "submit", intern, "Not")
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


def test_form_saves_second_reviewer(intern, lawyer, second, case_factory):
    t = TaskType.objects.first()
    data = form_data(t, intern, lawyer, second, case=case_factory().pk)
    r = login(lawyer).post(reverse("tasks:create"), data)
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
