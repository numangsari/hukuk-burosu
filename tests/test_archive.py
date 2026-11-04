import pytest
from django.urls import reverse

from apps.cases.models import ArchiveFolder, Case, CaseStatus, CaseType


@pytest.fixture
def archive_cases(db, admin_user, client_factory):
    c = client_factory(name="ARŞİV MÜVEKKİLİ")
    # 1. Açık dava dosyası (Açık 1 / 1)
    c1 = Case.objects.create(
        client=c,
        case_type=CaseType.CIVIL,
        authority="İstanbul 1. Asliye Hukuk",
        official_no="2026/10",
        subject="TAZMİNAT DAVASI",
        archive_folder_no="Açık 1",
        archive_no="1",
        status=CaseStatus.OPEN,
        responsible_lawyer=admin_user,
        created_by=admin_user,
    )
    # 2. Açık dava dosyası (Açık 1 / 3) -> 2 numara boşta kalacak
    c2 = Case.objects.create(
        client=c,
        case_type=CaseType.CIVIL,
        authority="İstanbul 1. Asliye Hukuk",
        official_no="2026/11",
        subject="TAPU İPTALİ",
        archive_folder_no="Açık 1",
        archive_no="3",
        status=CaseStatus.OPEN,
        responsible_lawyer=admin_user,
        created_by=admin_user,
    )
    # 3. Kapalı dava dosyası (Kapalı 5 / 12)
    c3 = Case.objects.create(
        client=c,
        case_type=CaseType.CRIMINAL,
        authority="İstanbul 2. Ağır Ceza",
        official_no="2024/50",
        subject="CEZA DAVASI",
        archive_folder_no="Kapalı 5",
        archive_no="12",
        status=CaseStatus.CLOSED,
        responsible_lawyer=admin_user,
        created_by=admin_user,
    )
    # 4. İcra dosyası (İcra 2 / 5)
    c4 = Case.objects.create(
        client=c,
        case_type=CaseType.ENFORCEMENT,
        authority="İstanbul 3. İcra Dairesi",
        official_no="2026/500",
        subject="İLAMSIZ TAKİP",
        archive_folder_no="İcra 2",
        archive_no="5",
        status=CaseStatus.OPEN,
        responsible_lawyer=admin_user,
        created_by=admin_user,
    )
    # 5. Arşiv yeri eksik dosya
    c5 = Case.objects.create(
        client=c,
        case_type=CaseType.MEDIATION,
        authority="Arabuluculuk Bürosu",
        official_no="2026/99",
        subject="İŞÇİLİK ALACAĞI",
        archive_folder_no="",
        archive_no="",
        status=CaseStatus.OPEN,
        responsible_lawyer=admin_user,
        created_by=admin_user,
    )
    return c1, c2, c3, c4, c5


def test_archive_list_scopes_and_views(client, admin_user, archive_cases):
    client.force_login(admin_user)
    c1, c2, c3, c4, c5 = archive_cases

    url = reverse("archive:list")

    # all scope
    resp = client.get(url)
    assert resp.status_code == 200
    assert len(resp.context["cases"]) == 5

    # open scope
    resp = client.get(url + "?scope=open")
    assert resp.status_code == 200
    assert c1 in resp.context["cases"]
    assert c2 in resp.context["cases"]
    assert c3 not in resp.context["cases"]

    # closed scope
    resp = client.get(url + "?scope=closed")
    assert resp.status_code == 200
    assert c3 in resp.context["cases"]
    assert c1 not in resp.context["cases"]

    # enforcement scope
    resp = client.get(url + "?scope=enforcement")
    assert resp.status_code == 200
    assert c4 in resp.context["cases"]
    assert c1 not in resp.context["cases"]

    # missing scope
    resp = client.get(url + "?scope=missing")
    assert resp.status_code == 200
    assert c5 in resp.context["cases"]
    assert c1 not in resp.context["cases"]

    # Klasör filtresi
    resp = client.get(url + "?klasor=Açık 1")
    assert resp.status_code == 200
    assert len(resp.context["cases"]) == 2

    # Gezgin görünümü
    resp = client.get(url + "?view=explorer")
    assert resp.status_code == 200
    assert "folder_list" in resp.context
    assert len(resp.context["folder_list"]) >= 3


def test_archive_folder_detail_and_missing_numbers(client, admin_user, archive_cases):
    client.force_login(admin_user)
    c1, c2, _, _, _ = archive_cases

    url = reverse("archive:folder_detail", kwargs={"folder_name": "Açık 1"})
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["folder_name"] == "Açık 1"
    assert resp.context["total_cases"] == 2
    # 1 ve 3 dolu, 2 boş olmalı!
    assert 2 in resp.context["missing_numbers"]
    assert resp.context["next_suggested"] == 4


def test_archive_location_update(client, admin_user, archive_cases):
    from apps.cases.models import ArchiveFolder

    client.force_login(admin_user)
    _, _, _, _, c5 = archive_cases
    ArchiveFolder.objects.create(name="Açık ARABULUCULUK 1", kind="open", capacity=8)

    url = reverse("archive:update_location", kwargs={"pk": c5.pk})
    resp = client.get(url)
    assert resp.status_code == 200

    resp = client.post(
        url,
        {"archive_folder_no": "Açık ARABULUCULUK 1", "archive_no": "7"},
    )
    assert resp.status_code == 302
    c5.refresh_from_db()
    assert c5.archive_folder_no == "Açık ARABULUCULUK 1"
    assert c5.archive_no == "7"
    assert c5.archive_reference == "Açık ARABULUCULUK 1 / 7"


def test_archive_labels_view(client, admin_user, archive_cases):
    client.force_login(admin_user)
    c1, c2, _, _, _ = archive_cases

    # Klasör sırtlığı
    resp = client.get(reverse("archive:labels") + "?klasor=Açık 1&tip=folder")
    assert resp.status_code == 200
    assert "Açık 1" in resp.content.decode()

    # Dosya etiketleri
    resp = client.get(reverse("archive:labels") + f"?dosya={c1.pk}&dosya={c2.pk}&tip=case")
    assert resp.status_code == 200
    assert "Açık 1 / 1" in resp.content.decode()
    assert "Açık 1 / 3" in resp.content.decode()


def test_archive_excel_export(client, admin_user, archive_cases):
    client.force_login(admin_user)
    url = reverse("archive:export")
    resp = client.get(url)
    assert resp.status_code == 200
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp["Content-Type"]
    )


def test_archive_filter_bar_client_and_folder_visibility(client, admin_user):
    client.force_login(admin_user)
    url = reverse("archive:list")

    # 1. Dava sekmesinde: Klasör seçimi ve Müvekkil seçimi olmamalı
    resp_dava = client.get(url + "?scope=dava")
    assert resp_dava.status_code == 200
    assert resp_dava.context["show_client_filter"] is False
    content_dava = resp_dava.content.decode()
    assert 'name="klasor"' not in content_dava
    assert 'name="muvekkil"' not in content_dava

    # 2. Tümü sekmesinde: Klasör seçimi ve Müvekkil seçimi olmamalı
    resp_all = client.get(url + "?scope=all")
    assert resp_all.status_code == 200
    assert resp_all.context["show_client_filter"] is False
    content_all = resp_all.content.decode()
    assert 'name="klasor"' not in content_all
    assert 'name="muvekkil"' not in content_all

    # 3. Müvekkile Özel sekmesinde: Yalnızca burada Müvekkil seçimi olmalı
    resp_client = client.get(url + "?scope=client_specific")
    assert resp_client.status_code == 200
    assert resp_client.context["show_client_filter"] is True
    content_client = resp_client.content.decode()
    assert 'name="klasor"' not in content_client
    assert 'name="muvekkil"' in content_client


def test_archive_search_narrowed_to_folder_and_client(
    client, admin_user, client_factory, case_factory
):
    client.force_login(admin_user)
    c_ahmet = client_factory(kind="company", title="Ahmet Yılmaz İnşaat")
    c_mehmet = client_factory(kind="person", first_name="Mehmet", last_name="Demir")

    folder_a = ArchiveFolder.objects.create(name="Özel Klasör Alfa", kind="open", capacity=10)
    folder_b = ArchiveFolder.objects.create(name="Beta Klasörü", kind="open", capacity=10)

    case_factory(
        client=c_ahmet,
        archive_folder_no=folder_a.name,
        archive_no="1",
        subject="Özel Alacak Davası",
        authority="İstanbul 3. Asliye Ticaret",
    )
    case_factory(
        client=c_mehmet,
        archive_folder_no=folder_b.name,
        archive_no="1",
        subject="Kira Tahliye",
        authority="Bakırköy 1. Sulh Hukuk",
    )

    url = reverse("archive:list")

    # 1. Klasör adı ile arama: bulmalı
    resp = client.get(url, {"q": "Alfa"})
    names = [f["archive_folder_no"] for f in resp.context["folder_list"]]
    assert "Özel Klasör Alfa" in names
    assert "Beta Klasörü" not in names

    # 2. Müvekkil adı ile arama: bulmalı
    resp = client.get(url, {"q": "Ahmet Yılmaz"})
    names = [f["archive_folder_no"] for f in resp.context["folder_list"]]
    assert "Özel Klasör Alfa" in names
    assert "Beta Klasörü" not in names

    # 3. Mahkeme / Merci ile arama: daraltıldığı için filtrelememeli / eşleşmemeli
    resp = client.get(url, {"q": "Ticaret"})
    names = [f["archive_folder_no"] for f in resp.context["folder_list"]]
    assert "Özel Klasör Alfa" not in names

    # 4. Dava konusu ile arama: daraltıldığı için eşleşmemeli
    resp = client.get(url, {"q": "Tahliye"})
    names = [f["archive_folder_no"] for f in resp.context["folder_list"]]
    assert "Beta Klasörü" not in names


def test_archive_status_filter_governed_by_physical_state(client, admin_user):
    client.force_login(admin_user)
    folder_open = ArchiveFolder.objects.create(
        name="Açık Test 1", kind="open", physical_state="open", capacity=10
    )
    folder_closed = ArchiveFolder.objects.create(
        name="Kapalı Test 1", kind="open", physical_state="closed", capacity=10
    )
    folder_single = ArchiveFolder.objects.create(
        name="Arabuluculuk Test 1", kind="open", physical_state="single", capacity=10
    )

    url = reverse("archive:list")

    # 1. Tümü (durum parametresiz) -> hepsi görünmeli
    resp_all = client.get(url)
    names_all = [f["archive_folder_no"] for f in resp_all.context["folder_list"]]
    assert folder_open.name in names_all
    assert folder_closed.name in names_all
    assert folder_single.name in names_all

    # 2. durum=open -> Açık ve Ayrımsız (single) görünmeli, Kapalı görünmemeli
    resp_open = client.get(url, {"durum": "open"})
    names_open = [f["archive_folder_no"] for f in resp_open.context["folder_list"]]
    assert folder_open.name in names_open
    assert folder_single.name in names_open
    assert folder_closed.name not in names_open

    # 3. durum=closed -> Yalnızca Kapalı görünmeli, Açık ve Ayrımsız (single) gizlenmeli
    resp_closed = client.get(url, {"durum": "closed"})
    names_closed = [f["archive_folder_no"] for f in resp_closed.context["folder_list"]]
    assert folder_closed.name in names_closed
    assert folder_open.name not in names_closed
    assert folder_single.name not in names_closed
