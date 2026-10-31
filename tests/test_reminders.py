import datetime as dt
import io

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.agenda.services import system_events
from apps.cases.models import Hearing, Service
from apps.notifications import services
from apps.notifications.models import Notification
from apps.office.models import TaskType
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_reminder_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def task_factory(case_factory, intern, lawyer):
    def create(**kwargs):
        defaults = {
            "task_type": TaskType.objects.get(name="Müvekkil görüşmesi"),
            "title": "Örnek iş",
            "case": case_factory(),
            "assignee": intern,
            "reviewer": lawyer,
            "due_date": timezone.localdate() + dt.timedelta(days=1),
        }
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    return create


def test_review_deadline_goes_to_reviewer(task_factory, lawyer, intern):
    task_factory(status="review")
    assert services.send_daily_reminders() == 1
    assert Notification.objects.get().user == lawyer
    assert not intern.notifications.exists()
    assert services.send_daily_reminders() == 0


def test_long_task_title_does_not_stop_reminders(task_factory):
    task_factory(title="A" * 300)
    assert services.send_daily_reminders() == 1
    assert len(Notification.objects.get().title) == 300


@pytest.mark.parametrize("kind", ["hearing", "service"])
def test_new_case_date_is_reminded_after_first_scan(
    case_factory, kind, django_capture_on_commit_callbacks
):
    case = case_factory()
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    services.run_daily_reminders_once()
    assert not Notification.objects.exists()
    with django_capture_on_commit_callbacks(execute=True):
        if kind == "hearing":
            Hearing.objects.create(
                case=case, starts_at=timezone.make_aware(dt.datetime.combine(tomorrow, dt.time(9)))
            )
        else:
            Service.objects.create(
                case=case,
                kind="post",
                subject="Örnek tebligat",
                served_on=timezone.localdate(),
                deadline=tomorrow,
            )
    services.run_daily_reminders_once()
    assert Notification.objects.count() == 2


def test_new_task_is_reminded_after_first_page_scan(
    task_factory, django_capture_on_commit_callbacks
):
    task_factory()
    services.run_daily_reminders_once()
    assert Notification.objects.count() == 1
    with django_capture_on_commit_callbacks(execute=True):
        second = task_factory(title="Gün içinde eklenen")
    services.run_daily_reminders_once()
    assert Notification.objects.count() == 2
    assert Notification.objects.filter(url=second.get_absolute_url()).exists()


def test_changed_due_date_refreshes_reminder(task_factory, django_capture_on_commit_callbacks):
    task = task_factory()
    services.run_daily_reminders_once()
    with django_capture_on_commit_callbacks(execute=True):
        task.due_date = timezone.localdate()
        task.save(update_fields=["due_date"])
    services.run_daily_reminders_once()
    assert Notification.objects.count() == 2
    assert "bugün" in Notification.objects.first().title


def test_submit_routes_new_deadline_to_reviewer(
    task_factory, lawyer, django_capture_on_commit_callbacks
):
    task = task_factory()
    services.run_daily_reminders_once()
    with django_capture_on_commit_callbacks(execute=True):
        task.status = "review"
        task.save(update_fields=["status"])
    services.run_daily_reminders_once()
    assert lawyer.notifications.filter(kind="deadline").count() == 1


def test_unfinished_service_deadlines_remind_both_responsible_users(case_factory, lawyer, intern):
    case = case_factory()
    today = timezone.localdate()
    for days, done in [(-1, False), (1, False), (0, True), (3, False)]:
        Service.objects.create(
            case=case,
            kind="post",
            subject="Örnek tebligat",
            served_on=today,
            deadline=today + dt.timedelta(days=days),
            is_done=done,
        )
    assert services.send_daily_reminders() == 4
    assert lawyer.notifications.count() == intern.notifications.count() == 2
    assert all("Tebligat" in notice.title for notice in Notification.objects.all())
    assert services.send_daily_reminders() == 0


def test_today_and_tomorrow_hearings_are_reminded(case_factory):
    case = case_factory()
    today = timezone.localdate()
    for days, status in [(0, "planned"), (1, "planned"), (-1, "planned"), (0, "cancelled")]:
        starts_at = timezone.make_aware(
            dt.datetime.combine(today + dt.timedelta(days=days), dt.time(9))
        )
        Hearing.objects.create(case=case, starts_at=starts_at, status=status)
    assert services.send_daily_reminders() == 4
    assert Notification.objects.filter(title__startswith="Bugün").count() == 2
    assert Notification.objects.filter(title__startswith="Yarın").count() == 2


def test_failed_scan_can_be_retried(monkeypatch):
    attempts = []

    def scan():
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("Örnek geçici hata")
        return 0

    monkeypatch.setattr(services, "send_daily_reminders", scan)
    with pytest.raises(RuntimeError):
        services.run_daily_reminders_once()
    services.run_daily_reminders_once()
    assert len(attempts) == 2


def test_scheduled_command_works_without_open_page(task_factory):
    task_factory()
    output = io.StringIO()
    call_command("send_reminders", stdout=output)
    assert Notification.objects.count() == 1
    assert "1 hatırlatma" in output.getvalue()
    call_command("send_reminders", stdout=output)
    assert Notification.objects.count() == 1


def test_open_task_deadlines_appear_on_calendar(task_factory, lawyer_client):
    today = timezone.localdate()
    active = task_factory(title="Aktif örnek iş", due_date=today)
    review = task_factory(title="Kontroldeki örnek iş", due_date=today, status="review")
    task_factory(title="Bitmiş örnek iş", due_date=today, status="done")
    task_factory(title="Dışarıdaki örnek iş", due_date=today + dt.timedelta(days=7))
    events = system_events(today, today + dt.timedelta(days=7))
    assert {event.url for event in events} == {active.get_absolute_url(), review.get_absolute_url()}
    assert all(event.source == "task" and event.all_day for event in events)
    for route in ["agenda:calendar", "core:home"]:
        html = lawyer_client.get(reverse(route)).content.decode()
        assert "Görev son günü: Aktif örnek iş" in html
        assert "Görev son günü: Kontroldeki örnek iş" in html
