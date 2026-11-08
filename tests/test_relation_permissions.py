import pytest
from django.test import Client as HttpClient
from django.urls import reverse

from apps.accounts.forms import RolePermissionsForm
from apps.accounts.models import User
from apps.core.permission_registry import has_perm
from apps.office.models import OfficeSettings

from .conftest import make_user

pytestmark = pytest.mark.django_db


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def grant(key, *tokens):
    OfficeSettings.load().set_role_permission(key, tokens)


def other_case(case_factory, client_factory):
    stranger = make_user("baska", User.Role.LAWYER)
    return case_factory(client=client_factory(responsible_lawyer=stranger, responsible_intern=None))


def test_responsible_gets_permission_only_on_own_case(lawyer, intern, case_factory, client_factory):
    case = case_factory()
    foreign = other_case(case_factory, client_factory)
    # Hiçbir ilişki seçili değilken rol kuralı geçerli: avukat/stajyer kapalı dosyayı açamaz.
    assert not has_perm(lawyer, "cases.reopen", case)
    grant("cases.reopen", "responsible")
    assert has_perm(lawyer, "cases.reopen", case)
    assert not has_perm(lawyer, "cases.reopen", foreign)
    assert not has_perm(lawyer, "cases.reopen")  # nesnesiz denetim yalnızca rolle
    assert not has_perm(intern, "cases.reopen", case)  # yardımcı sorumlu seçili değil
    grant("cases.reopen", "assistant")
    assert has_perm(intern, "cases.reopen", case)
    assert not has_perm(lawyer, "cases.reopen", case)


def test_non_scoped_permission_ignores_relations(lawyer, case_factory):
    case = case_factory()
    grant("tasks.routines", "responsible")
    assert not has_perm(lawyer, "tasks.routines", case)


def test_reopen_view_allows_responsible_and_blocks_stranger(lawyer, case_factory, client_factory):
    case = case_factory()
    foreign = other_case(case_factory, client_factory)
    grant("cases.reopen", "responsible")
    c = login(lawyer)
    assert c.post(reverse("cases:reopen", args=[foreign.pk]), {"stage": "x"}).status_code == 403
    assert c.post(reverse("cases:reopen", args=[case.pk]), {"stage": "x"}).status_code != 403


def test_accounting_edit_by_relation(lawyer, intern, case_factory, client_factory):
    case = case_factory()
    foreign = other_case(case_factory, client_factory)
    grant("accounting.edit", "responsible")  # avukat ve stajyer rolü kapalı
    url = reverse("accounting:create")
    c = login(lawyer)
    assert c.get(url, {"dosya": case.pk}).status_code == 200
    assert c.get(url, {"dosya": foreign.pk}).status_code == 403
    assert c.get(url).status_code == 403
    assert login(intern).get(url, {"dosya": case.pk}).status_code == 403


def test_settings_form_saves_relation_columns(admin_user):
    form = RolePermissionsForm(
        {
            "perm:cases.reopen:responsible": "on",
            "perm:cases.reopen:assistant": "on",
            "perm:tasks.routines:responsible": "on",  # dosya bazlı değil: yok sayılır
        }
    )
    assert form.is_valid()
    form.save()
    saved = OfficeSettings.load().role_permissions
    assert {"responsible", "assistant"} <= set(saved["cases.reopen"])
    assert "responsible" not in saved["tasks.routines"]
