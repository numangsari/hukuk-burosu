import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agenda.services import hearing_events
from apps.cases.models import (
    Case,
    CaseEvent,
    CaseType,
    Hearing,
    HearingKind,
    HearingStatus,
)
from apps.imports.models import PortalCase
from apps.imports.portal_case_sync import sync_record_hearings


@pytest.fixture
def case_with_hearings(db, admin_user, client_factory):
    c = client_factory(name="TEST MÜVEKKİL")
    case = Case.objects.create(
        client=c,
        case_type=CaseType.CIVIL,
        authority="İstanbul 1. Asliye Hukuk Mahkemesi",
        official_no="2026/100",
        subject="ALACAK DAVASI",
        archive_folder_no="Açık 1",
        archive_no="10",
        responsible_lawyer=admin_user,
        created_by=admin_user,
    )
    now = timezone.now()
    # 1. Gelecek duruşma
    h1 = Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=now + dt.timedelta(days=2),
        authority="İstanbul 1. Asliye Hukuk Mahkemesi",
        room="Salon 1",
        status=HearingStatus.PLANNED,
        created_by=admin_user,
    )
    # 2. Geçmişte ve sonuç bekleyen duruşma
    h2 = Hearing.objects.create(
        case=case,
        kind=HearingKind.PRELIMINARY,
        starts_at=now - dt.timedelta(days=1),
        authority="İstanbul 1. Asliye Hukuk Mahkemesi",
        status=HearingStatus.PLANNED,
        created_by=admin_user,
    )
    # 3. Geçmiş ve yapılmış duruşma
    h3 = Hearing.objects.create(
        case=case,
        kind=HearingKind.DISCOVERY,
        starts_at=now - dt.timedelta(days=5),
        authority="Keşif Mahalli",
        status=HearingStatus.HELD,
        result="Keşif icra edildi, bilirkişi raporu bekleniyor.",
        created_by=admin_user,
    )
    return case, h1, h2, h3


def test_hearing_list_scopes_and_filters(client, admin_user, case_with_hearings):
    client.force_login(admin_user)
    case, h1, h2, h3 = case_with_hearings

    url = reverse("hearings:list")

    # Varsayılan: upcoming
    resp = client.get(url)
    assert resp.status_code == 200
    assert h1 in resp.context["hearings"]
    assert h2 not in resp.context["hearings"]
    assert h3 not in resp.context["hearings"]

    # pending_result
    resp = client.get(url + "?scope=pending_result")
    assert resp.status_code == 200
    assert h2 in resp.context["hearings"]
    assert h1 not in resp.context["hearings"]

    # past
    resp = client.get(url + "?scope=past")
    assert resp.status_code == 200
    assert h3 in resp.context["hearings"]
    assert h1 not in resp.context["hearings"]

    # all
    resp = client.get(url + "?scope=all")
    assert resp.status_code == 200
    assert len(resp.context["hearings"]) == 3

    # Arama filtresi
    resp = client.get(url + "?scope=all&q=Keşif")
    assert resp.status_code == 200
    assert h3 in resp.context["hearings"]
    assert h1 not in resp.context["hearings"]


def test_hearing_standalone_create(client, admin_user, case_with_hearings):
    client.force_login(admin_user)
    case, _, _, _ = case_with_hearings

    url = reverse("hearings:create")
    resp = client.get(url)
    assert resp.status_code == 200

    now = timezone.now()
    starts = (now + dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    data = {
        "case": case.pk,
        "kind": HearingKind.HEARING,
        "starts_at": starts,
        "authority": "İstanbul 1. Asliye Hukuk",
        "room": "Salon 3",
        "notes": "Tanıklar dinlenecek",
    }
    resp = client.post(url, data)
    assert resp.status_code == 302
    assert Hearing.objects.filter(case=case, room="Salon 3", notes="Tanıklar dinlenecek").exists()


def test_hearing_create_in_window_refreshes_parent(client, admin_user, case_with_hearings):
    client.force_login(admin_user)
    case, _, _, _ = case_with_hearings
    response = client.post(
        reverse("hearings:create") + "?pencere=1",
        {"case": case.pk, "kind": HearingKind.HEARING, "starts_at": "2027-01-04 10:00"},
    )
    assert response.status_code == 200
    assert "window.parent.location.reload()" in response.content.decode()
    assert Hearing.objects.filter(case=case, starts_at__year=2027).exists()


def test_hearing_result_modal_and_event_creation(client, admin_user, case_with_hearings):
    client.force_login(admin_user)
    case, _, h2, _ = case_with_hearings

    url = reverse("hearings:result", kwargs={"pk": h2.pk})
    resp = client.get(url)
    assert resp.status_code == 200

    post_data = {
        "status": HearingStatus.POSTPONED,
        "result": "Dava sonraki celseye ertelendi.",
    }
    resp = client.post(url, post_data)
    assert resp.status_code == 302

    h2.refresh_from_db()
    assert h2.status == HearingStatus.POSTPONED
    assert h2.result == "Dava sonraki celseye ertelendi."

    # Dosya zaman çizelgesine CaseEvent eklenmiş olmalı
    event = CaseEvent.objects.filter(case=case, kind=CaseEvent.Kind.HEARING).last()
    assert event is not None
    assert "Dava sonraki celseye ertelendi." in event.description


def test_hearing_edit_and_delete(client, admin_user, case_with_hearings):
    client.force_login(admin_user)
    case, h1, _, _ = case_with_hearings

    # Edit
    edit_url = reverse("hearings:edit", kwargs={"pk": h1.pk})
    resp = client.get(edit_url)
    assert resp.status_code == 200

    now = timezone.now()
    starts = (now + dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M")
    resp = client.post(
        edit_url,
        {
            "kind": HearingKind.EXPERT,
            "starts_at": starts,
            "authority": "Bilirkişi Odası",
            "room": "B-2",
            "notes": "Hesap incelemesi",
        },
    )
    assert resp.status_code == 302
    h1.refresh_from_db()
    assert h1.kind == HearingKind.EXPERT
    assert h1.room == "B-2"

    # Delete
    del_url = reverse("hearings:delete", kwargs={"pk": h1.pk})
    resp = client.post(del_url)
    assert resp.status_code == 302
    assert not Hearing.objects.filter(pk=h1.pk).exists()


def test_hearing_case_detail_partial_actions(client, admin_user, case_with_hearings):
    client.force_login(admin_user)
    case, _, _, _ = case_with_hearings

    # Case detail sayfasında duruşmalar sekmesi
    resp = client.get(case.get_absolute_url())
    assert resp.status_code == 200
    assert "Duruşmalar" in resp.content.decode()

    # Duruşma ekleme (case record view)
    add_url = reverse("cases:hearing_add", kwargs={"pk": case.pk})
    now = timezone.now()
    resp = client.post(
        add_url,
        {
            "kind": HearingKind.HEARING,
            "starts_at": (now + dt.timedelta(days=3)).strftime("%Y-%m-%d %H:%M"),
            "authority": case.authority,
            "room": "Salon 5",
            "notes": "Detaydan eklendi",
        },
    )
    assert resp.status_code == 200
    new_h = Hearing.objects.filter(case=case, room="Salon 5").first()
    assert new_h is not None

    # Sonuç kaydetme (case record view)
    res_url = reverse("cases:hearing_result", kwargs={"pk": case.pk, "item_pk": new_h.pk})
    resp = client.post(
        res_url,
        {"status": HearingStatus.HELD, "result": "Karar verildi."},
    )
    assert resp.status_code == 200
    new_h.refresh_from_db()
    assert new_h.status == HearingStatus.HELD

    # Silme (case record view)
    del_url = reverse("cases:hearing_delete", kwargs={"pk": case.pk, "item_pk": new_h.pk})
    resp = client.post(del_url)
    assert resp.status_code == 200
    assert not Hearing.objects.filter(pk=new_h.pk).exists()


def test_hearing_excel_export(client, admin_user, case_with_hearings):
    client.force_login(admin_user)
    url = reverse("hearings:export")
    resp = client.get(url)
    assert resp.status_code == 200
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp["Content-Type"]
    )


def test_uyap_hearing_sync(db, admin_user, case_with_hearings):
    case, _, _, _ = case_with_hearings
    pc = PortalCase.objects.create(
        fingerprint="test-hearing-fp-1",
        authority="İstanbul 1. Asliye Hukuk",
        number="2026/100",
        case=case,
        data={
            "durusmalar": [
                {
                    "kayitId": 987654321,
                    "tarihSaat": "2026-11-20 14:30:00.0",
                    "yerelBirimAd": "İstanbul 1. Asliye Hukuk Mahkemesi",
                    "islemTuruAciklama": "Duruşma",
                    "salon": "Salon 4",
                    "islemSonucuAciklama": "Günü Verildi",
                }
            ]
        },
    )
    sync_record_hearings(case, pc, default_user=admin_user)
    synced = Hearing.objects.filter(case=case, portal_ref="987654321").first()
    assert synced is not None
    assert synced.room == "Salon 4"
    assert synced.status == HearingStatus.PLANNED


def test_agenda_hearing_events(db, admin_user, case_with_hearings):
    today = timezone.localdate()
    events = hearing_events(today - dt.timedelta(days=10), today + dt.timedelta(days=10))
    assert len(events) >= 3
    assert any(ev.source == "hearing" for ev in events)
