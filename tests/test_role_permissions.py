import datetime as dt

import pytest
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.core import permission_registry as registry
from apps.imports.models import PortalNotice
from apps.office.models import OfficeSettings, TaskType
from apps.tasks.models import PetitionSample, Task

from .conftest import make_user

pytestmark = pytest.mark.django_db


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def grant(key, *roles):
    OfficeSettings.load().set_role_permission(key, roles)


# ---- kayıt defteri -----------------------------------------------------------------------


def test_every_permission_has_defaults_and_unique_key():
    keys = [p.key for p in registry.PERMISSIONS]
    assert len(keys) == len(set(keys))
    for perm in registry.PERMISSIONS:
        assert set(perm.default) <= set(registry.ALL_ROLES)


def test_admin_always_has_every_permission_even_if_unchecked(admin_user, lawyer):
    for perm in registry.PERMISSIONS:
        grant(perm.key, "lawyer")
        assert registry.has_perm(admin_user, perm.key)
        assert registry.has_perm(lawyer, perm.key)
    superuser = User.objects.create_user(username="super", role="lawyer", is_superuser=True)
    assert registry.has_perm(superuser, "hearings.delete")


def test_unsaved_permission_uses_default_and_inactive_user_has_none(lawyer, intern):
    assert registry.has_perm(lawyer, "notices.create_task")  # varsayılan: herkes
    assert not registry.has_perm(lawyer, "cases.delete")  # varsayılan: yalnızca yönetici
    lawyer.is_active = False
    assert not registry.has_perm(lawyer, "notices.create_task")
    assert not registry.has_perm(None, "notices.create_task")


# ---- görev -------------------------------------------------------------------------------


def test_routine_management_follows_matrix(admin_user, lawyer, intern):
    url = reverse("tasks:routines")
    senior = make_user("kidemli5", "senior")
    assert login(senior).get(url).status_code == 200  # varsayılan: yönetici + kıdemli
    assert login(lawyer).get(url).status_code == 403
    grant("tasks.routines", "lawyer")
    assert login(lawyer).get(url).status_code == 200
    assert login(senior).get(url).status_code == 403  # kıdemli işaretlenmedi


def test_task_edit_and_delete_permissions(admin_user, lawyer, intern, case_factory):
    case = case_factory()
    task = Task.objects.create(
        task_type=TaskType.objects.first(),
        title="T",
        case=case,
        assignee=intern,
        reviewer=lawyer,
        due_date=timezone.localdate() + dt.timedelta(days=3),
        created_by=admin_user,
    )
    edit = reverse("tasks:update", args=[task.pk])
    assert login(lawyer).get(edit).status_code == 403
    grant("tasks.edit_any", "lawyer")
    assert login(lawyer).get(edit).status_code == 200
    delete = reverse("tasks:delete", args=[task.pk])
    assert login(lawyer).post(delete).status_code == 403
    grant("tasks.delete_any", "lawyer")
    assert login(lawyer).post(delete).status_code == 302
    assert not Task.objects.filter(pk=task.pk).exists()


def test_reviewer_required_unless_assignee_role_can_close_without_review(
    admin_user, lawyer, intern, case_factory
):
    from apps.tasks import services
    from apps.tasks.forms import TaskForm

    case = case_factory()

    def data(assignee):
        return {
            "task_type": TaskType.objects.first().pk,
            "title": "Kontrol denemesi",
            "case": case.pk,
            "assignee": assignee.pk,
            "reviewer": "",
            "due_date": (timezone.localdate() + dt.timedelta(days=2)).isoformat(),
            "requires_accounting": "no",
        }

    assert "reviewer" in TaskForm(data(lawyer)).errors  # varsayılan: kimse işaretli değil
    grant("tasks.close_without_review", "lawyer")
    assert TaskForm(data(lawyer)).is_valid()
    assert "reviewer" in TaskForm(data(intern)).errors  # stajyer işaretli değil
    task = TaskForm(data(lawyer)).save()
    assert "close" in [a.key for a in services.available_actions(task, lawyer)]
    grant("tasks.close_without_review")  # hiç rol: kontrolcü herkes için zorunlu
    assert "reviewer" in TaskForm(data(lawyer)).errors


# ---- tebligat ----------------------------------------------------------------------------


def test_notice_actions_follow_matrix(admin_user, lawyer, intern):
    notice = PortalNotice.objects.create(fingerprint="perm-notice", subject="Tebligat")
    no_task = reverse("notice_no_task", args=[notice.pk])
    create = reverse("notice_task_create", args=[notice.pk])
    assert login(intern).get(no_task).status_code == 200  # varsayılan: herkes
    assert login(intern).get(create).status_code in (200, 302)
    grant("notices.no_task", "lawyer")
    grant("notices.create_task", "lawyer")
    assert login(intern).get(no_task).status_code == 403
    assert login(intern).get(create).status_code == 403
    assert login(lawyer).get(no_task).status_code == 200
    assert login(admin_user).get(no_task).status_code == 200  # yönetici her zaman


# ---- silme ve diğer işlemler -----------------------------------------------------------------


def test_delete_actions_follow_matrix(admin_user, lawyer, case_factory):
    case = case_factory()
    client_pk = case.client.pk
    url = reverse("cases:delete", args=[case.pk])
    assert login(lawyer).post(url).status_code == 403
    grant("cases.delete", "lawyer")
    assert login(lawyer).post(url).status_code == 302
    other = case_factory()
    assert login(lawyer).post(reverse("clients:delete", args=[other.client.pk])).status_code == 403
    grant("clients.delete", "lawyer")
    assert (
        login(lawyer).post(reverse("clients:delete", args=[client_pk + 10000])).status_code == 404
    )


def test_petition_pool_delete_follows_matrix(admin_user, lawyer, intern):
    sample = PetitionSample.objects.create(
        title="Örnek", original_name="o.pdf", size=1, created_by=admin_user
    )
    url = reverse("tasks:pool_delete", args=[sample.pk])
    assert login(intern).post(url).status_code == 403
    grant("petition_pool.delete_any", "intern")
    assert login(intern).post(url).status_code == 302


# ---- ekran ---------------------------------------------------------------------------------------


def test_matrix_page_is_admin_only_and_lists_every_permission(admin_user, lawyer):
    url = reverse("accounts:settings")
    html = login(admin_user).get(url, {"bolum": "yetkiler"}).content.decode()
    for perm in registry.PERMISSIONS:
        assert perm.label in html
    for _role, label in registry.ROLES:
        assert label in html
    assert login(lawyer).post(url, {"section": "yetkiler"}).status_code in (302, 403)
    grant("cases.view_all", "senior")
    assert not registry.has_perm(lawyer, "cases.view_all")
    login(lawyer).post(url, {"section": "yetkiler", "perm:cases.view_all:lawyer": "on"})
    assert not registry.has_perm(lawyer, "cases.view_all")  # yönetici olmayan kaydedemez
