import datetime as dt

import pytest
from django.urls import reverse

from apps.cases.models import Case, Seizure
from apps.core.module_stats import module_stats

pytestmark = pytest.mark.django_db


def make_enforcement(case_factory, **kw):
    defaults = {"case_type": "enforcement", "client_role": "creditor", "stage": "started"}
    defaults.update(kw)
    return case_factory(**defaults)


def add_seizure(case, user, **kw):
    today = dt.date.today()
    defaults = {
        "debtor": "Borçlu",
        "kind": "salary",
        "state": "salary_applied",
        "seized_on": today,
        "renewal_on": today + dt.timedelta(days=10),
        "created_by": user,
    }
    defaults.update(kw)
    return Seizure.objects.create(case=case, **defaults)


def names(response):
    return {c.pk for c in response.context["cases"]}


def test_lists_only_enforcement_cases(admin_user, client, case_factory):
    icra = make_enforcement(case_factory)
    dava = case_factory(case_type="civil")
    client.force_login(admin_user)
    got = names(client.get(reverse("enforcement:list")))
    assert icra.pk in got and dava.pk not in got


def test_filters_by_role_seizure_and_notice(admin_user, client, case_factory):
    creditor = make_enforcement(case_factory)
    debtor = make_enforcement(case_factory, client_role="debtor")
    add_seizure(creditor, admin_user)
    client.force_login(admin_user)
    url = reverse("enforcement:list")
    assert names(client.get(url, {"sifat": "debtor"})) == {debtor.pk}
    assert names(client.get(url, {"haciz": "var"})) == {creditor.pk}
    assert names(client.get(url, {"haciz": "yok"})) == {debtor.pk}
    assert names(client.get(url, {"haciz": "salary"})) == {creditor.pk}
    assert names(client.get(url, {"haciz": "yenileme"})) == {creditor.pk}
    assert names(client.get(url, {"tebligat": "1"})) == set()


def test_stage_and_status_filters(admin_user, client, case_factory):
    open_case = make_enforcement(case_factory, stage="seizure")
    closed = make_enforcement(case_factory)
    Case.objects.filter(pk=closed.pk).update(status="closed")
    client.force_login(admin_user)
    url = reverse("enforcement:list")
    assert names(client.get(url, {"asama": "seizure"})) == {open_case.pk}
    assert names(client.get(url)) == {open_case.pk}
    assert names(client.get(url, {"status": "all"})) == {open_case.pk, closed.pk}


def test_strip_counts_are_same_for_every_role(admin_user, intern, client, case_factory):
    case = make_enforcement(case_factory)
    add_seizure(case, admin_user)
    from django.core.cache import cache

    cache.clear()
    stats = dict(module_stats("enforcement"))
    assert stats["Açık icra"] == 1 and stats["Hacizli"] == 1


def test_export_and_unauthenticated(admin_user, client, case_factory):
    make_enforcement(case_factory)
    url = reverse("enforcement:list")
    assert client.get(url).status_code == 302
    client.force_login(admin_user)
    assert client.get(url, {"export": "xlsx"}).status_code == 200


@pytest.mark.parametrize(
    "key", ["home", "cases", "clients", "tasks", "hearings", "accounting", "archive", "notices"]
)
def test_module_stats_do_not_fail(key, db):
    from django.core.cache import cache

    cache.clear()
    assert module_stats(key)


def test_settings_sections_render_for_admin(admin_user, client):
    client.force_login(admin_user)
    url = reverse("accounts:settings")
    for section in ("kullanici_analizi", "monitor", "yetkiler", "gorev_turleri", "kullanicilar"):
        assert client.get(url, {"bolum": section}).status_code == 200, section


def test_db_dump_export_admin_only(admin_user, lawyer_client, client, monkeypatch):
    def fake_dump(target):
        target.write_bytes(b"PGDMP-test")

    monkeypatch.setattr("apps.backups.views.dump_database", fake_dump)
    url = reverse("backups:export_db_dump")
    assert lawyer_client.get(url).status_code == 403
    client.force_login(admin_user)
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == b"PGDMP-test"
    assert 'filename="db.dump"' in response["Content-Disposition"]


def test_portal_review_page_removed(admin_user, client):
    client.force_login(admin_user)
    html = client.get(reverse("accounts:settings"), {"bolum": "monitor"}).content.decode()
    assert "UYAP ve UETS inceleme" not in html
