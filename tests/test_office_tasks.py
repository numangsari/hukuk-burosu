import datetime as dt

import pytest
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.office.models import OfficeSettings, TaskType
from apps.tasks import services
from apps.tasks.models import Task, TaskStatus

from .conftest import make_user

pytestmark = pytest.mark.django_db


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def office_task(assignee, reviewer=None, creator=None, **kw):
    defaults = {
        "task_type": TaskType.objects.get(name="Müvekkil Görüşmesi"),
        "title": "Ofis malzemesi sipariş et",
        "assignee": assignee,
        "reviewer": reviewer,
        "due_date": timezone.localdate() + dt.timedelta(days=3),
        "created_by": creator or assignee,
    }
    defaults.update(kw)
    return Task.objects.create(**defaults)


def test_office_task_has_no_case_or_client(intern):
    t = office_task(intern)
    assert t.case_id is None and t.client_id is None and t.is_office_task


def test_task_form_requires_case(lawyer, intern):
    r = login(lawyer).post(
        reverse("tasks:create"),
        {
            "task_type": TaskType.objects.first().pk,
            "title": "Arşiv düzenle",
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "due_date": "2026-11-10",
            "requires_accounting": "no",
        },
    )
    assert r.status_code == 200 and "case" in r.context["form"].errors
    assert not Task.objects.exists()


@pytest.mark.parametrize("mode", ["public", "restricted"])
def test_office_task_visible_only_to_assignee_reviewer_and_admin(mode, lawyer, intern, admin_user):
    office = OfficeSettings.load()
    office.case_visibility_mode = mode
    office.save()
    other = make_user("baska", "lawyer")
    secretary = make_user("sekreter", "secretary")
    t = office_task(intern, reviewer=lawyer)
    for user, expected in [
        (intern, 200),
        (lawyer, 200),
        (admin_user, 200),
        (other, 404),
        (secretary, 404),
    ]:
        assert login(user).get(t.get_absolute_url()).status_code == expected, user.username


def test_office_task_listed_only_for_involved_users(lawyer, intern, admin_user):
    office_task(intern, reviewer=lawyer, title="Gizli ofis isi")
    other = make_user("baska", "lawyer")
    url = reverse("tasks:list") + "?kapsam=tumu&sekme=aktif"
    assert (
        "GIZLI OFIS"
        in login(admin_user).get(url).content.decode().replace("İ", "I").replace("ı", "i").upper()
    )
    assert (
        "GIZLI OFIS"
        in login(intern).get(url).content.decode().replace("İ", "I").replace("ı", "i").upper()
    )
    assert (
        "GIZLI OFIS"
        not in login(other).get(url).content.decode().replace("İ", "I").replace("ı", "i").upper()
    )


def test_office_task_full_cycle_without_case(lawyer, intern):
    t = office_task(intern, reviewer=lawyer)
    services.perform(t, "submit", intern)
    services.perform(t, "approve", lawyer)
    services.perform(t, "close", intern, "Tamamlandı")
    t.refresh_from_db()
    assert t.status == TaskStatus.DONE


def test_office_task_detail_and_home_render(lawyer, intern):
    t = office_task(intern, reviewer=lawyer)
    html = login(intern).get(t.get_absolute_url()).content.decode()
    assert "Ofis içi görev" in html
    assert login(intern).get(reverse("core:home")).status_code == 200


def test_office_task_delete_redirects_to_list(lawyer):
    t = office_task(lawyer, creator=lawyer)
    r = login(lawyer).post(reverse("tasks:delete", args=[t.pk]))
    assert r.status_code == 302 and r.url == reverse("tasks:list")
    assert not Task.objects.exists()


def test_petition_template_unavailable_for_office_task(lawyer, intern):
    t = office_task(intern, reviewer=lawyer)
    assert login(lawyer).get(reverse("tasks:petition_template", args=[t.pk])).status_code == 404
