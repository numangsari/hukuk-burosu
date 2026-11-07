import datetime as dt
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.agenda import google_sync
from apps.cases.models import Hearing, HearingKind, HearingStatus
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db

CAL_ID = "test-cal@group.calendar.google.com"


@pytest.fixture
def api_enabled():
    office = OfficeSettings.load()
    office.google_calendar_api_enabled = True
    office.google_calendar_id = CAL_ID
    office.google_service_account_json = '{"project_id": "test"}'
    office.save()
    return office


@pytest.fixture
def service(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(google_sync, "get_calendar_service", lambda: (svc, CAL_ID))
    return svc


def _hearing(case_factory, **kwargs):
    return Hearing.objects.create(
        case=case_factory(),
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(days=2),
        **kwargs,
    )


def test_failed_sync_marks_pending_and_retry_clears_it(case_factory, api_enabled, service):
    events = service.events.return_value
    events.insert.return_value.execute.side_effect = ConnectionError("ağ yok")
    hearing = _hearing(case_factory)

    assert google_sync.sync_hearing_to_google(hearing) is None
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is True
    assert hearing.google_event_id == ""

    events.insert.return_value.execute.side_effect = None
    events.insert.return_value.execute.return_value = {"id": "ev-1"}
    result = google_sync.retry_pending_google_syncs()

    assert result == {"success": True, "total": 1, "synced": 1, "errors": 0}
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is False
    assert hearing.google_event_id == "ev-1"
    # Yeniden deneme mükerrer etkinlik açmaz: ikinci çalıştırmada bekleyen kayıt yok.
    assert google_sync.retry_pending_google_syncs()["total"] == 0
    assert events.insert.return_value.execute.call_count == 2


def test_retry_keeps_pending_when_still_failing(case_factory, api_enabled, service):
    service.events.return_value.insert.return_value.execute.side_effect = ConnectionError()
    hearing = _hearing(case_factory, google_sync_pending=True)

    result = google_sync.retry_pending_google_syncs()

    assert result["errors"] == 1 and result["synced"] == 0
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is True


def test_cancelled_hearing_network_error_does_not_raise(case_factory, api_enabled, service):
    service.events.return_value.delete.return_value.execute.side_effect = ConnectionError()
    hearing = _hearing(case_factory, status=HearingStatus.CANCELLED, google_event_id="ev-9")

    assert google_sync.sync_hearing_to_google(hearing) is None
    hearing.refresh_from_db()
    # Kimlik korunur ki sonraki denemede Google'daki etkinlik silinebilsin.
    assert hearing.google_event_id == "ev-9"
    assert hearing.google_sync_pending is True

    service.events.return_value.delete.return_value.execute.side_effect = None
    google_sync.retry_pending_google_syncs()
    hearing.refresh_from_db()
    assert hearing.google_event_id == ""
    assert hearing.google_sync_pending is False


def test_disabled_api_does_not_mark_pending(case_factory):
    hearing = _hearing(case_factory)
    assert google_sync.sync_hearing_to_google(hearing) is None
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is False


def test_unavailable_service_while_enabled_marks_pending(case_factory, api_enabled, monkeypatch):
    monkeypatch.setattr(google_sync, "get_calendar_service", lambda: (None, None))
    hearing = _hearing(case_factory)
    google_sync.sync_hearing_to_google(hearing)
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is True


def test_retry_command_is_silent_when_api_disabled(case_factory, capsys):
    _hearing(case_factory, google_sync_pending=True)
    call_command("retry_google_sync")
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_retry_command_reports_counts(case_factory, api_enabled, service, capsys):
    service.events.return_value.insert.return_value.execute.return_value = {"id": "ev-2"}
    hearing = _hearing(case_factory, google_sync_pending=True)
    # Komut, yeni değişen kayıtları arka plan işine bırakır; eski kaydı yeniden dener.
    Hearing.objects.filter(pk=hearing.pk).update(
        updated_at=timezone.now() - dt.timedelta(minutes=10)
    )
    call_command("retry_google_sync")
    assert "1 bekleyen eşitlemeden 1 başarılı" in capsys.readouterr().out
