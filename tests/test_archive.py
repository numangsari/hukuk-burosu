import pytest
from django.urls import reverse

from apps.cases.models import Case, CaseStatus, CaseType


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
    client.force_login(admin_user)
    _, _, _, _, c5 = archive_cases

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
