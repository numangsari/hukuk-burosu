import datetime as dt
from decimal import Decimal

import pytest
from auditlog.models import LogEntry
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import EntryKind, LedgerEntry
from apps.cases.models import Hearing
from apps.office.models import TaskType
from apps.reports.definitions import REPORTS
from apps.search.views import search
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


# --- Arama -------------------------------------------------------------------------------
def test_search_turkish_insensitive(client_factory, case_factory):
    c = client_factory(first_name="Işıl", last_name="Çağlayan")
    case_factory(client=c, subject="İŞÇİLİK ALACAĞI", official_no="2026/123 E.")
    for q in ("isil", "IŞIL", "caglayan", "çağlayan"):
        assert [x.pk for x in search(q)["clients"]] == [c.pk], q
    assert len(search("iscilik")["cases"]) == 1
    assert len(search("işçilik alacağı")["cases"]) == 1
    assert len(search("2026/123")["cases"]) == 1
    assert search("x") == {}  # en az 2 karakter


def test_search_typo_tolerance(client_factory):
    client_factory(
        kind="company", title="Yıldırım İnşaat Taahhüt A.Ş.", first_name="", last_name=""
    )
    assert search("yildirm insaat")["clients"]  # trigram ile yakın eşleşme


def test_search_views(lawyer_client, client_factory):
    client_factory(first_name="Mehmet", last_name="Öztürk")
    r = lawyer_client.get(
        reverse("search:search"), {"q": "ozturk", "canli": 1}, HTTP_HX_REQUEST="true"
    )
    assert "MEHMET ÖZTÜRK" in r.content.decode()
    r = lawyer_client.get(reverse("search:search"), {"q": "ozturk"})
    assert r.context["total"] == 1


def test_search_page_kind_filter_and_sort(lawyer_client, client_factory, case_factory):
    a = client_factory(first_name="Zeki", last_name="Deneme")
    b = client_factory(first_name="Ahmet", last_name="Deneme")
    case_factory(client=a, subject="Deneme davası")
    url = reverse("search:search")
    r = lawyer_client.get(url, {"q": "deneme"})
    counts = {param: n for param, _, n in r.context["kinds"]}
    assert counts["muvekkil"] == 2 and counts["dosya"] == 1
    # Tür süzgeci yalnızca seçilen türü getirir; sayılar yine hepsini gösterir.
    r = lawyer_client.get(url, {"q": "deneme", "tur": "muvekkil"}, HTTP_HX_REQUEST="true")
    assert set(r.context["r"]) == {"clients"}
    assert r.context["total"] == 3
    # Ada göre sıralama
    r = lawyer_client.get(url, {"q": "deneme", "tur": "muvekkil", "sirala": "ad"})
    assert [c.pk for c in r.context["r"]["clients"]] == [b.pk, a.pk]
    r = lawyer_client.get(url, {"q": "deneme", "tur": "muvekkil", "sirala": "yeni"})
    assert [c.pk for c in r.context["r"]["clients"]] == [b.pk, a.pk]


def test_search_page_paginates_kind_and_previews_all(lawyer, client_factory):
    from apps.search.views import PREVIEW_LIMIT

    lawyer.page_size = 5
    lawyer.save()
    for i in range(PREVIEW_LIMIT + 2):
        client_factory(first_name=f"Kişi{i:02d}", last_name="Sayfalı")
    c = login(lawyer)
    url = reverse("search:search")
    # Tümü: türden ilk sonuçlar + tümünü gör bağlantısı
    r = c.get(url, {"q": "sayfali"})
    assert len(r.context["r"]["clients"]) == PREVIEW_LIMIT
    assert r.context["more"]["clients"][0] == PREVIEW_LIMIT + 2
    # Tür sekmesi: kullanıcının sayfa boyutuyla sayfa sayfa, hepsi görülebilir
    r = c.get(url, {"q": "sayfali", "tur": "muvekkil", "page": 3})
    assert r.context["paginator"].num_pages == 3
    assert len(r.context["r"]["clients"]) == 2


# --- Aktivite ----------------------------------------------------------------------------
def test_activity_records_changes_and_login(lawyer, admin_user, client_factory, client):
    c = client_factory()
    c.notes = "Yeni not"
    c.save()
    client.force_login(lawyer)
    client.post(
        reverse("accounts:login")
    )  # oturum zaten açık; giriş kaydı force_login ile değil sinyalle
    from django.contrib.auth.signals import user_logged_in

    user_logged_in.send(sender=type(lawyer), request=None, user=lawyer)
    assert LogEntry.objects.filter(action=LogEntry.Action.ACCESS, actor=lawyer).exists()
    # Detay sayfasında kayıt geçmişi
    r = login(lawyer).get(c.get_absolute_url())
    assert any(e.action == LogEntry.Action.UPDATE for e in r.context["history"])


def test_activity_visibility(lawyer, admin_user, intern, client_factory):
    from auditlog.context import set_actor

    with set_actor(intern):
        client_factory(first_name="Stajyerin")
    with set_actor(lawyer):
        client_factory(first_name="Avukatın")
    mine = login(lawyer).get(reverse("activity:list")).context["entries"]
    assert {e.actor_id for e in mine} == {lawyer.pk}
    everyone = login(admin_user).get(reverse("activity:list")).context["entries"]
    assert {lawyer.pk, intern.pk} <= {e.actor_id for e in everyone}


def test_user_password_changes_not_logged(admin_user):
    admin_user.set_password("9999")
    admin_user.save()
    for e in LogEntry.objects.get_for_object(admin_user):
        assert "password" not in (e.changes or {})


# --- Raporlar ----------------------------------------------------------------------------
@pytest.fixture
def report_data(case_factory, lawyer, intern):
    case = case_factory(archive_no="2026/0007", subject="Kira alacağı")
    c = case.client
    for kind, amount, day in [
        (EntryKind.FEE, "10000", 1),
        (EntryKind.EXPENSE, "500", 2),
        (EntryKind.COLLECTION, "3000", 15),
        (EntryKind.TRUST_IN, "2000", 20),
    ]:
        LedgerEntry.objects.create(
            client=c, case=case, kind=kind, amount=Decimal(amount), date=dt.date(2026, 10, day)
        )
    Task.objects.create(
        task_type=TaskType.objects.first(),
        title="Gecikmiş iş",
        case=case,
        assignee=intern,
        reviewer=lawyer,
        due_date=timezone.localdate() - dt.timedelta(days=2),
    )
    Hearing.objects.create(
        case=case, starts_at=timezone.now() + dt.timedelta(days=3), authority="Adliye"
    )
    return case


@pytest.mark.parametrize("key", list(REPORTS))
def test_every_report_previews_and_exports(key, admin_user, report_data):
    c = login(admin_user)
    url = reverse("reports:report", args=[key])
    params = {"goster": 1}
    if key == "cari-ekstre":
        params["client"] = report_data.client_id
    r = c.get(url, params)
    assert r.status_code == 200 and r.context["result"] is not None
    x = c.get(url, {**params, "format": "xlsx"})
    assert x["Content-Type"].startswith("application/vnd.openxml") and x.content[:2] == b"PK"
    p = c.get(url, {**params, "format": "pdf"})
    assert p["Content-Type"] == "application/pdf" and p.content[:4] == b"%PDF"


def test_report_values(admin_user, report_data):
    c = login(admin_user)
    r = c.get(
        reverse("reports:report", args=["cari-ekstre"]),
        {"goster": 1, "client": report_data.client_id, "start": "2026-10-10"},
    )
    res = r.context["result"]
    assert res.rows[0][1] == "Devir" and res.rows[0][5] == Decimal("10500")
    assert res.rows[-1][5] == Decimal("5500")
    r = c.get(reverse("reports:report", args=["gorevler"]), {"goster": 1, "status": "overdue"})
    assert [row[1] for row in r.context["result"].rows] == ["GECİKMİŞ İŞ"]
    r = c.get(reverse("reports:report", args=["dosya-son-durum"]), {"goster": 1})
    row = r.context["result"].rows[0]
    assert row[1] == "2026/0007" and row[4] == 1
    assert "Sonraki duruşma" not in [column.label for column in r.context["result"].columns]


def test_financial_reports_hidden_without_permission(intern, report_data):
    assert not intern.can_view_balances
    c = login(intern)
    keys = set(c.get(reverse("reports:index")).context["reports"])
    assert keys == {"gorevler", "dosya-listesi", "dosya-son-durum", "haciz-takibi"}
    assert c.get(reverse("reports:report", args=["donem-muhasebe"])).status_code == 403


def test_reports_do_not_query_per_row(
    admin_user, case_factory, client_factory, django_assert_max_num_queries
):
    """Kayıt sayısı artınca sorgu sayısı artmamalı (borçlular ve dosya son durumu)."""
    for i in range(12):
        c = client_factory(first_name=f"Kişi{i}")
        k = case_factory(client=c)
        LedgerEntry.objects.create(
            client=c, case=k, kind="fee", amount=Decimal("100"), date=dt.date(2026, 10, 1)
        )
        LedgerEntry.objects.create(
            client=c, case=k, kind="trust_in", amount=Decimal("40"), date=dt.date(2026, 10, 2)
        )
    from apps.reports.definitions import build_client_cases, build_debtors

    with django_assert_max_num_queries(4):
        res = build_debtors({}, admin_user)
    assert len(res.rows) == 12 and res.rows[0][3] == Decimal("40")
    with django_assert_max_num_queries(3):
        res = build_client_cases({}, admin_user)
    assert len(res.rows) == 12


def test_case_options_endpoint(lawyer_client, case_factory, client_factory):
    a = client_factory(first_name="A")
    k1 = case_factory(client=a)
    case_factory(client=a, status="closed")
    url = reverse("tasks:case_options")
    assert lawyer_client.get(url).json()["cases"] == []  # müvekkilsiz liste sunucudan gelir
    assert [c["id"] for c in lawyer_client.get(url, {"client": a.pk}).json()["cases"]] == [k1.pk]
    assert len(lawyer_client.get(url, {"client": a.pk, "all": 1}).json()["cases"]) == 2
    one = lawyer_client.get(url, {"id": k1.pk}).json()["cases"][0]
    assert one["client"] == a.pk and one["lawyer"] == k1.responsible_lawyer_id
    assert lawyer_client.get(url, {"id": "x"}).json()["cases"] == []
