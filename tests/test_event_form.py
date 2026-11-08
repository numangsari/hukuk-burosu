import pytest
from django.utils import timezone

from apps.cases.forms import HearingStandaloneForm
from apps.cases.models import HearingKind

pytestmark = pytest.mark.django_db


def data(**kw):
    base = {"kind": "other", "starts_at": "2026-12-01T10:00", "title": "Toplantı"}
    base.update(kw)
    return base


def test_expert_kind_removed_and_offsite_meeting_added(admin_user):
    kinds = [value for value, _ in HearingStandaloneForm(user=admin_user).fields["kind"].choices]
    assert HearingKind.EXPERT not in kinds
    assert HearingKind.CLIENT_MEETING_OFFSITE in kinds
    assert HearingStandaloneForm(user=admin_user).fields["kind"].choices


def test_no_authority_field_and_new_event_starts_today(admin_user):
    form = HearingStandaloneForm(user=admin_user)
    assert "authority" not in form.fields
    assert form.initial["starts_at"].date() == timezone.localdate()


def test_listed_kinds_require_case_and_attendance(admin_user, case_factory):
    form = HearingStandaloneForm(
        data(kind="hearing", title="", assigned_to=admin_user.pk, attendance="attend"),
        user=admin_user,
    )
    assert not form.is_valid() and "case" in form.errors
    case = case_factory()
    ok = HearingStandaloneForm(
        data(kind="hearing", title="", case=case.pk, assigned_to=admin_user.pk, attendance=""),
        user=admin_user,
    )
    assert not ok.is_valid() and "attendance" in ok.errors
    ok = HearingStandaloneForm(
        data(
            kind="hearing", title="", case=case.pk, assigned_to=admin_user.pk, attendance="remote"
        ),
        user=admin_user,
    )
    assert ok.is_valid(), ok.errors
    hearing = ok.save()
    assert hearing.is_remote and hearing.authority == case.authority


def test_other_kinds_ignore_attendance_and_keep_title_rule(admin_user):
    form = HearingStandaloneForm(data(attendance="excuse"), user=admin_user)
    assert form.is_valid(), form.errors
    hearing = form.save()
    assert not hearing.excuse_submitted and not hearing.is_remote
    empty = HearingStandaloneForm(data(title=""), user=admin_user)
    assert not empty.is_valid()
