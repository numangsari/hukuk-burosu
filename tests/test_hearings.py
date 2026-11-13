import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agenda.services import hearing_events
from apps.cases.models import (
    Case,
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
                    "islemSonucuAciklama": "Günü Verildi",
                }
            ]
        },
    )
    sync_record_hearings(case, pc, default_user=admin_user)
    synced = Hearing.objects.filter(case=case, portal_ref="987654321").first()
    assert synced is not None
    assert synced.status == HearingStatus.PLANNED


def test_agenda_hearing_events(db, admin_user, case_with_hearings):
    today = timezone.localdate()
    events = hearing_events(today - dt.timedelta(days=10), today + dt.timedelta(days=10))
    assert len(events) >= 3
    assert any(ev.source == "hearing" for ev in events)


def _uyap_record(case, when, fp="test-google-mark"):
    return PortalCase.objects.create(
        fingerprint=fp,
        authority="İstanbul 1. Asliye Hukuk",
        number="2026/200",
        case=case,
        data={
            "durusmalar": [
                {
                    "kayitId": 555,
                    "tarihSaat": when,
                    "yerelBirimAd": "İstanbul 1. Asliye Hukuk Mahkemesi",
                    "islemTuruAciklama": "Duruşma",
                    "islemSonucuAciklama": "Günü Verildi",
                }
            ]
        },
    )


def test_uyap_hearing_marked_for_google_when_calendar_enabled(db, admin_user, case_with_hearings):
    from apps.office.models import OfficeSettings

    case, _, _, _ = case_with_hearings
    office = OfficeSettings.load()
    office.google_calendar_api_enabled = True
    office.save()
    pc = _uyap_record(case, "2027-03-10 10:00:00.0")
    sync_record_hearings(case, pc, default_user=admin_user)
    hearing = Hearing.objects.get(case=case, portal_ref="555")
    assert hearing.google_sync_pending is True

    # Takvime yazıldıktan sonra UYAP'ta saat değişirse yeniden işaretlenir.
    Hearing.objects.filter(pk=hearing.pk).update(google_sync_pending=False)
    pc.data["durusmalar"][0]["tarihSaat"] = "2027-03-10 14:00:00.0"
    pc.save()
    sync_record_hearings(case, pc, default_user=admin_user)
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is True
    assert timezone.localtime(hearing.starts_at).hour == 14


def test_uyap_hearing_not_marked_when_calendar_disabled(db, admin_user, case_with_hearings):
    case, _, _, _ = case_with_hearings
    pc = _uyap_record(case, "2027-03-10 10:00:00.0", fp="test-google-off")
    sync_record_hearings(case, pc, default_user=admin_user)
    assert Hearing.objects.get(case=case, portal_ref="555").google_sync_pending is False
