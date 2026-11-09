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


def test_lists_only_creditor_cases(admin_user, client, case_factory):
    creditor = make_enforcement(case_factory)
    debtor = make_enforcement(case_factory, client_role="debtor")
    client.force_login(admin_user)
    got = names(client.get(reverse("enforcement:list")))
    assert creditor.pk in got and debtor.pk not in got


def test_filters_by_seizure_and_notice(admin_user, client, case_factory):
    with_seizure = make_enforcement(case_factory, stage="seizure")
    without = make_enforcement(case_factory, stage="seizure")
    add_seizure(with_seizure, admin_user)
    client.force_login(admin_user)
    url = reverse("enforcement:list")
    tab = {"sekme": "haciz"}
    assert names(client.get(url, {**tab, "haciz": "var"})) == {with_seizure.pk}
    assert names(client.get(url, {**tab, "haciz": "yok"})) == {without.pk}
    assert names(client.get(url, {**tab, "haciz": "yenileme"})) == {with_seizure.pk}


def test_tabs_split_cases_by_stage(admin_user, client, case_factory):
    notice = make_enforcement(case_factory, stage="order_served")
    seizure = make_enforcement(case_factory, stage="seizure")
    stopped = make_enforcement(case_factory, stage="suspended")
    dormant = make_enforcement(case_factory, stage="dormant")
    closed = make_enforcement(case_factory, stage="seizure")
    Case.objects.filter(pk=closed.pk).update(status="closed")
    client.force_login(admin_user)
    url = reverse("enforcement:list")
    assert names(client.get(url)) == {notice.pk}
    assert names(client.get(url, {"sekme": "tebligat"})) == {notice.pk}
    assert names(client.get(url, {"sekme": "haciz"})) == {seizure.pk}
    assert names(client.get(url, {"sekme": "durdurulan"})) == {stopped.pk}
    assert names(client.get(url, {"sekme": "islemsiz"})) == {dormant.pk, closed.pk}
    assert names(client.get(url, {"sekme": "bilinmeyen"})) == {notice.pk}


def test_debtor_and_third_party_tabs(admin_user, client, case_factory):
    creditor = make_enforcement(case_factory)
    debtor = make_enforcement(case_factory, client_role="debtor", stage="seizure")
    third = make_enforcement(case_factory, client_role="other")
    client.force_login(admin_user)
    url = reverse("enforcement:list")
    assert names(client.get(url, {"sekme": "borclu"})) == {debtor.pk}
    assert names(client.get(url, {"sekme": "ucuncu"})) == {third.pk}
    assert names(client.get(url)) == {creditor.pk}
    for tab in ("borclu", "ucuncu"):
        assert client.get(url, {"sekme": tab, "export": "xlsx"}).status_code == 200


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


def test_seizure_badges_colors(admin_user, case_factory):
    from apps.cases.seizure_types import kind_badges

    case = make_enforcement(case_factory, stage="seizure")
    add_seizure(case, admin_user, kind="salary", state="salary_unemployed", seized_on=None)
    add_seizure(case, admin_user, kind="bank", state="bank_seized", bank_name="X")
    add_seizure(case, admin_user, kind="vehicle", state="vehicle_none", seized_on=None)
    add_seizure(case, admin_user, kind="vehicle", state="vehicle_seized", plate="34ABC1")
    add_seizure(case, admin_user, kind="notice", state="notice_requested", notice_stage="89/1")
    by_kind = {b["kind"]: b["level"] for b in kind_badges(list(case.seizures.all()))}
    assert by_kind["salary"] == "neg"
    assert by_kind["bank"] == "pos"
    assert by_kind["vehicle"] == "pos"  # biri olumluysa yeşil
    assert by_kind["notice"] == "wait"
    assert by_kind["property"] == "none"


def test_columns_per_tab(admin_user, client, case_factory):
    case = make_enforcement(case_factory, stage="seizure", uyap_stage="")
    closed = make_enforcement(case_factory, uyap_stage="Kapalı (Haricen Tahsil)")
    Case.objects.filter(pk=closed.pk).update(status="closed")
    client.force_login(admin_user)
    url = reverse("enforcement:list")
    html = client.get(url, {"sekme": "haciz"}).content.decode()
    assert "Haciz durumu" in html and "seizure-badge" in html and case.archive_no is not None
    html = client.get(url, {"sekme": "islemsiz"}).content.decode()
    assert "Kapanma nedeni (UYAP)" in html and "Haricen Tahsil" in html
    assert "Haciz durumu" not in html.split("<thead>")[1].split("</thead>")[0]
    html = client.get(url, {"sekme": "ucuncu"}).content.decode()
    assert "Müvekkil (sıfatı)" in html
    for tab in ("haciz", "islemsiz", "borclu", "ucuncu"):
        assert client.get(url, {"sekme": tab, "export": "xlsx"}).status_code == 200


def test_uyap_closing_reason_fallbacks(case_factory):
    from apps.cases.enforcement import uyap_closing_reason

    open_case = make_enforcement(case_factory)
    assert uyap_closing_reason(open_case) == ""
    closed = make_enforcement(case_factory, uyap_stage="Kapalı (Takipten Vazgeçme)")
    Case.objects.filter(pk=closed.pk).update(status="closed")
    closed.refresh_from_db()
    assert uyap_closing_reason(closed) == "Takipten Vazgeçme"


def test_scope_toggle_mine_only(admin_user, lawyer, client, case_factory):
    mine = make_enforcement(case_factory, responsible_lawyer=admin_user)
    other = make_enforcement(case_factory, responsible_lawyer=lawyer)
    client.force_login(admin_user)
    url = reverse("enforcement:list")
    assert names(client.get(url)) == {mine.pk, other.pk}
    assert names(client.get(url, {"kapsam": "bana"})) == {mine.pk}
    got = names(client.get(reverse("cases:list"), {"kapsam": "bana"}))
    assert mine.pk in got and other.pk not in got
    html = client.get(reverse("clients:list")).content.decode()
    assert "Bana atanmış" in html
    html = client.get(reverse("agenda:calendar"), {"view": "list"}).content.decode()
    assert "Bana atanmış" in html
    assert (
        client.get(reverse("agenda:calendar"), {"view": "list", "kapsam": "bana"}).status_code
        == 200
    )
