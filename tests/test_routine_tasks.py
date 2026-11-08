import datetime as dt

import pytest
from django.core.management import call_command
from django.test import Client as HttpClient
from django.urls import reverse

from apps.accounts.models import User
from apps.tasks import routines
from apps.tasks.models import RoutineTask, Task

from .conftest import make_user

pytestmark = pytest.mark.django_db

MONDAY = dt.date(2026, 11, 2)  # 2 Kasım 2026 pazartesi


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def routine(assignee, **kw):
    defaults = {
        "title": "Haftalık duruşma dosyası hazırlığı",
        "assignee": assignee,
        "frequency": RoutineTask.Frequency.WEEKLY,
        "weekday": 0,
    }
    defaults.update(kw)
    return RoutineTask.objects.create(**defaults)


# ---- tarih hesabı ----------------------------------------------------------------------


def test_weekly_occurrence_is_latest_matching_weekday(intern):
    r = routine(intern, weekday=0)
    assert routines.latest_occurrence(r, MONDAY) == MONDAY
    assert routines.latest_occurrence(r, MONDAY + dt.timedelta(days=3)) == MONDAY
    assert routines.latest_occurrence(r, MONDAY + dt.timedelta(days=7)) == MONDAY + dt.timedelta(
        days=7
    )


def test_monthly_occurrence_and_short_months(intern):
    r = routine(intern, frequency=RoutineTask.Frequency.MONTHLY, weekday=None, month_day=31)
    assert routines.latest_occurrence(r, dt.date(2026, 2, 28)) == dt.date(2026, 2, 28)
    assert routines.latest_occurrence(r, dt.date(2026, 3, 30)) == dt.date(2026, 2, 28)
    assert routines.latest_occurrence(r, dt.date(2026, 3, 31)) == dt.date(2026, 3, 31)
    r.month_day = 15
    assert routines.latest_occurrence(r, dt.date(2026, 3, 10)) == dt.date(2026, 2, 15)


# ---- görev üretimi ---------------------------------------------------------------------


def test_creates_office_task_on_the_day(intern, lawyer):
    r = routine(intern, reviewer=lawyer, due_days=2)
    created, skipped = routines.create_due_tasks(MONDAY)
    assert (created, skipped) == (1, 0)
    t = Task.objects.get()
    assert t.case_id is None and t.assignee == intern and t.reviewer == lawyer
    assert t.due_date == MONDAY + dt.timedelta(days=2)
    assert t.title == "HAFTALIK DURUŞMA DOSYASI HAZIRLIĞI"
    assert t.task_type.name == "Rutin Görev" and not t.assignee_seen
    r.refresh_from_db()
    assert r.last_created_for == MONDAY


def test_runs_are_idempotent(intern):
    routine(intern)
    routines.create_due_tasks(MONDAY)
    assert routines.create_due_tasks(MONDAY) == (0, 0)
    assert Task.objects.count() == 1


def test_first_run_does_not_backfill_old_occurrences(intern):
    routine(intern)  # pazartesi; bugün çarşamba
    assert routines.create_due_tasks(MONDAY + dt.timedelta(days=2)) == (0, 0)
    assert not Task.objects.exists()


def test_missed_day_is_caught_up_within_three_days(intern):
    r = routine(intern)
    r.last_created_for = MONDAY - dt.timedelta(days=7)
    r.save()
    assert routines.create_due_tasks(MONDAY + dt.timedelta(days=2)) == (1, 0)
    assert Task.objects.get().due_date == MONDAY


def test_old_missed_occurrence_is_not_created(intern):
    r = routine(intern)
    r.last_created_for = MONDAY - dt.timedelta(days=14)
    r.save()
    # Pazartesi 3 günden eski: sunucu uzun süre kapalıydı, eski görev açılmaz.
    assert routines.create_due_tasks(MONDAY + dt.timedelta(days=5)) == (0, 0)


def test_inactive_routine_and_inactive_assignee_are_skipped(intern, lawyer):
    routine(intern, is_active=False)
    assert routines.create_due_tasks(MONDAY) == (0, 0)
    off = make_user("pasif", "intern")
    off.is_active = False
    off.save()
    routine(off, title="Pasif sorumlu")
    assert routines.create_due_tasks(MONDAY) == (0, 1)
    assert not Task.objects.exists()


def test_inactive_reviewer_is_dropped(intern):
    off = make_user("pasifkontrol", "lawyer")
    off.is_active = False
    off.save()
    routine(intern, reviewer=off)
    routines.create_due_tasks(MONDAY)
    assert Task.objects.get().reviewer_id is None


def test_management_command_runs(intern):
    routine(intern)
    call_command("create_routine_tasks")  # bugün pazartesi değilse görev açmaz, hata vermez


# ---- ekran -----------------------------------------------------------------------------


def test_only_admin_and_senior_manage_routines(admin_user, lawyer, intern):
    senior = make_user("kidemli", User.Role.SENIOR)
    url = reverse("tasks:routines")
    assert login(admin_user).get(url).status_code == 200
    assert login(senior).get(url).status_code == 200
    assert login(senior).get(reverse("tasks:routine_create")).status_code == 200
    for user in (lawyer, intern):
        assert login(user).get(url).status_code == 403
        assert login(user).get(reverse("tasks:routine_create")).status_code == 403


def type_data():
    task_type = routines.routine_task_type()
    return {"task_type": task_type.pk, "requires_accounting": "no"}


def test_admin_creates_weekly_routine(admin_user, intern, lawyer):
    r = login(admin_user).post(
        reverse("tasks:routine_create"),
        {
            **type_data(),
            "title": "Haftalık arşiv kontrolü",
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "frequency": "weekly",
            "weekday": "4",
            "month_day": "17",
            "due_days": "1",
            "is_active": "on",
        },
    )
    assert r.status_code == 302
    obj = RoutineTask.objects.get()
    assert obj.weekday == 4 and obj.month_day is None and obj.created_by == admin_user


def test_monthly_requires_day_and_weekly_requires_weekday(admin_user, intern):
    c = login(admin_user)
    base = {
        **type_data(),
        "title": "X",
        "assignee": intern.pk,
        "due_days": "0",
        "is_active": "on",
    }
    monthly = c.post(reverse("tasks:routine_create"), {**base, "frequency": "monthly"})
    weekly = c.post(reverse("tasks:routine_create"), {**base, "frequency": "weekly"})
    assert "month_day" in monthly.context["form"].errors
    assert "weekday" in weekly.context["form"].errors
    assert not RoutineTask.objects.exists()


def test_admin_edits_and_deletes_routine(admin_user, intern, lawyer):
    r = routine(intern)
    c = login(admin_user)
    resp = c.post(
        reverse("tasks:routine_update", args=[r.pk]),
        {
            **type_data(),
            "title": "Yeni ad",
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "frequency": "monthly",
            "month_day": "5",
            "due_days": "0",
        },
    )
    assert resp.status_code == 302, resp.context["form"].errors
    r.refresh_from_db()
    assert r.title == "Yeni ad" and r.month_day == 5 and r.weekday is None and not r.is_active
    assert c.post(reverse("tasks:routine_delete", args=[r.pk])).status_code == 302
    assert not RoutineTask.objects.exists()


def test_deleting_routine_keeps_generated_tasks(admin_user, intern):
    r = routine(intern)
    routines.create_due_tasks(MONDAY)
    login(admin_user).post(reverse("tasks:routine_delete", args=[r.pk]))
    assert Task.objects.count() == 1 and Task.objects.get().routine_id is None


def test_routine_create_in_popup_reloads_parent(admin_user, intern, lawyer):
    url = reverse("tasks:routine_create") + "?pencere=1"
    r = login(admin_user).post(
        url,
        {
            **type_data(),
            "title": "Pencere",
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "frequency": "weekly",
            "weekday": "0",
            "due_days": "0",
            "is_active": "on",
        },
    )
    assert r.status_code == 200, r.context["form"].errors
    assert b"window.parent.location.reload()" in r.content
    assert (
        RoutineTask.objects.filter(title="PENCERE").exists()
        or RoutineTask.objects.filter(title="Pencere").exists()
    )


def test_routine_form_asks_task_details_and_copies_them(
    admin_user, intern, lawyer, case_factory, tmp_path, settings
):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = tmp_path
    case = case_factory()
    third = make_user("ucuncu", User.Role.SENIOR)
    r = login(admin_user).post(
        reverse("tasks:routine_create"),
        {
            **type_data(),
            "requires_accounting": "yes",
            "title": "Dosya rutini",
            "case": case.pk,
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "second_reviewer": third.pk,
            "notes": "Rutin not",
            "document": SimpleUploadedFile("sablon.pdf", b"%PDF-1.4 x", "application/pdf"),
            "frequency": "weekly",
            "weekday": "0",
            "due_days": "2",
            "is_active": "on",
        },
    )
    assert r.status_code == 302, getattr(r, "context", None) and r.context["form"].errors
    created, _ = routines.create_due_tasks(MONDAY)
    assert created == 1
    task = Task.objects.get()
    assert task.case == case and task.client_id == case.client_id
    assert task.second_reviewer == third and task.requires_accounting is True
    assert task.events.filter(kind="note", comment="Rutin not").exists()
    assert task.documents.filter(original_name="sablon.pdf", is_current=True).count() == 1


def test_routine_second_reviewer_needs_first(admin_user, intern, lawyer):
    r = login(admin_user).post(
        reverse("tasks:routine_create"),
        {
            **type_data(),
            "title": "X",
            "assignee": intern.pk,
            "second_reviewer": lawyer.pk,
            "frequency": "weekly",
            "weekday": "0",
            "due_days": "0",
        },
    )
    assert "second_reviewer" in r.context["form"].errors
    assert not RoutineTask.objects.exists()
