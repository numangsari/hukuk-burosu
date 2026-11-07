import datetime as dt
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.agenda import google_sync
from apps.cases.models import Hearing, HearingKind
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
    svc.events.return_value.insert.return_value.execute.return_value = {"id": "ev-bg"}
    monkeypatch.setattr(google_sync, "get_calendar_service", lambda: (svc, CAL_ID))
    return svc


@pytest.fixture
def spawned(monkeypatch):
    """Arka plan iş parçacığı yerine işi toplar; testte elle çalıştırılır."""
    jobs = []
    monkeypatch.setattr(google_sync, "_spawn", lambda job, *args: jobs.append((job, args)))
    return jobs


def _hearing(case_factory, **kwargs):
    return Hearing.objects.create(
        case=case_factory(),
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(days=2),
        **kwargs,
    )


def test_default_test_mode_syncs_inside_the_call(case_factory, api_enabled, service):
    hearing = _hearing(case_factory)
    google_sync.queue_hearing_google_sync(hearing)
    hearing.refresh_from_db()
    assert hearing.google_event_id == "ev-bg"


def test_background_mode_marks_pending_and_defers_google_call(
    case_factory, api_enabled, service, spawned, settings, django_capture_on_commit_callbacks
):
    settings.GOOGLE_SYNC_BACKGROUND = True
    hearing = _hearing(case_factory)
    with django_capture_on_commit_callbacks(execute=True):
        google_sync.queue_hearing_google_sync(hearing)
    # İstek içinde Google'a gidilmez; kayıt bekliyor olarak işaretlenir ve iş kuyruğa alınır.
    assert service.events.return_value.insert.call_count == 0
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is True and hearing.google_event_id == ""
    assert len(spawned) == 1

    job, args = spawned[0]
    job(*args)
    hearing.refresh_from_db()
    assert hearing.google_event_id == "ev-bg"
    assert hearing.google_sync_pending is False


def test_background_failure_keeps_pending_for_retry(
    case_factory, api_enabled, service, spawned, settings, django_capture_on_commit_callbacks
):
    settings.GOOGLE_SYNC_BACKGROUND = True
    service.events.return_value.insert.return_value.execute.side_effect = ConnectionError("ağ yok")
    hearing = _hearing(case_factory)
    with django_capture_on_commit_callbacks(execute=True):
        google_sync.queue_hearing_google_sync(hearing)
    job, args = spawned[0]
    job(*args)
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is True and hearing.google_event_id == ""


def test_background_mode_does_nothing_when_api_disabled(
    case_factory, spawned, settings, django_capture_on_commit_callbacks
):
    settings.GOOGLE_SYNC_BACKGROUND = True
    hearing = _hearing(case_factory)
    with django_capture_on_commit_callbacks(execute=True):
        google_sync.queue_hearing_google_sync(hearing)
    hearing.refresh_from_db()
    assert hearing.google_sync_pending is False
    assert spawned == []


def test_queued_job_ignores_deleted_hearing(case_factory, api_enabled, service):
    hearing = _hearing(case_factory)
    pk = hearing.pk
    hearing.delete()
    google_sync._run_queued_sync(pk)
    assert service.events.return_value.insert.call_count == 0


def test_retry_skips_freshly_queued_hearings_to_avoid_duplicate_events(
    case_factory, api_enabled, service
):
    fresh = _hearing(case_factory, google_sync_pending=True)
    old = _hearing(case_factory, google_sync_pending=True)
    Hearing.objects.filter(pk=old.pk).update(updated_at=timezone.now() - dt.timedelta(minutes=10))

    result = google_sync.retry_pending_google_syncs(min_age_seconds=120)

    assert result["total"] == 1
    fresh.refresh_from_db()
    old.refresh_from_db()
    assert fresh.google_sync_pending is True and fresh.google_event_id == ""
    assert old.google_sync_pending is False and old.google_event_id == "ev-bg"


@pytest.mark.django_db(transaction=True)
def test_real_background_thread_completes_sync(case_factory, api_enabled, service, settings):
    import threading

    settings.GOOGLE_SYNC_BACKGROUND = True
    hearing = _hearing(case_factory)
    google_sync.queue_hearing_google_sync(hearing)
    for thread in [t for t in threading.enumerate() if t.name == "google-sync"]:
        thread.join(timeout=10)
    hearing.refresh_from_db()
    assert hearing.google_event_id == "ev-bg"
    assert hearing.google_sync_pending is False
