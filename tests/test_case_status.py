import datetime as dt

import pytest
from django.urls import reverse

from apps.cases import services, stages
from apps.cases.forms import CaseCloseForm
from apps.cases.models import Case, CaseEvent

TODAY = dt.date(2026, 11, 1)


def test_every_type_has_open_stages_and_closing_reasons():
    from apps.cases.models import CaseType

    for case_type in CaseType.values:
        assert stages.open_stages(case_type), case_type
        reasons = stages.closing_reasons(case_type)
        assert reasons and reasons[-1].key == "other" and "n" in reasons[-1].flags
        assert len({key for key, _ in stages.open_stages(case_type)}) == len(
            stages.open_stages(case_type)
        )
        assert len({r.key for r in reasons}) == len(reasons)


def test_new_case_is_open_with_first_stage(case_factory):
    case = case_factory(case_type="enforcement")
    assert case.status == "open" and case.stage == "started"
    assert case.status_summary == "Açık / Takip başlatıldı"


def test_change_stage_records_event(case_factory, lawyer):
    case = case_factory(case_type="civil")
    services.change_stage(case, "appeal", lawyer)
    case.refresh_from_db()
    assert case.stage == "appeal"
    event = case.events.get(kind=CaseEvent.Kind.STATUS)
    assert "Derdest" in event.title and "İstinaf" in event.title
    with pytest.raises(services.StatusError):
        services.change_stage(case, "started", lawyer)  # icra aşaması hukukta geçersiz


def _close_data(case, **kw):
    data = {"closing_reason": "waiver", "closed_on": TODAY.isoformat()}
    data.update(kw)
    return data


def test_close_form_requires_note_for_other_and_amount_details(case_factory):
    case = case_factory(case_type="civil")
    form = CaseCloseForm(_close_data(case, closing_reason="other"), case=case)
    assert not form.is_valid() and "closing_note" in form.errors
    form = CaseCloseForm(
        _close_data(case, closing_reason="settlement", closing_amount="1500"), case=case
    )
    assert not form.is_valid()
    assert {"closing_amount_date", "closing_accounted"} <= form.errors.keys()
    form = CaseCloseForm(
        _close_data(
            case,
            closing_reason="settlement",
            closing_amount="1500",
            closing_amount_date=TODAY.isoformat(),
            closing_accounted="0",
        ),
        case=case,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["closing_accounted"] is False


def test_amount_ignored_when_reason_has_no_payment_and_decision_only_for_judicial(case_factory):
    case = case_factory(case_type="civil")
    form = CaseCloseForm(_close_data(case, closing_amount="99"), case=case)
    assert form.is_valid() and form.cleaned_data["closing_amount"] is None
    assert {"decision_year", "decision_sequence"} <= form.fields.keys()
    consultancy = case_factory(case_type="consultancy", archive_no="9001")
    assert "decision_year" not in CaseCloseForm(case=consultancy).fields


def test_close_and_reopen_flow(lawyer_client, case_factory):
    case = case_factory(case_type="civil")
    url = reverse("cases:close", args=[case.pk])
    assert lawyer_client.get(url).status_code == 200
    response = lawyer_client.post(
        url,
        _close_data(
            case,
            closing_reason="full_accept",
            decision_date=TODAY.isoformat(),
            decision_year="2026",
            decision_sequence="55",
            closing_amount="1000",
            closing_amount_date=TODAY.isoformat(),
            closing_accounted="0",
        ),
    )
    assert response.status_code == 302
    case.refresh_from_db()
    assert case.status == "closed" and case.decision_no == "2026/55"
    assert case.closing_accounted is False and case.closed_on == TODAY
    assert case.status_summary.startswith("Kapalı / Davanın tamamen kabulü")
    page = lawyer_client.get(case.get_absolute_url())
    assert "Muhasebe kaydı bekliyor" in page.content.decode()
    # Kapalı dosya tekrar kapatılamaz, aşaması değişmez; avukat yeniden açamaz.
    assert lawyer_client.post(url, _close_data(case)).status_code == 302
    reopen = reverse("cases:reopen", args=[case.pk])
    lawyer_client.post(reopen, {"stage": "pending"})
    case.refresh_from_db()
    assert case.status == "closed"


def test_admin_reopens_case_and_clears_closing_data(admin_client_logged, case_factory, admin_user):
    case = case_factory(case_type="civil")
    services.close_case(
        case,
        {
            "closing_reason": "waiver",
            "closed_on": TODAY,
            "closing_note": "Müvekkil vazgeçti",
        },
        admin_user,
    )
    response = admin_client_logged.post(
        reverse("cases:reopen", args=[case.pk]), {"stage": "appeal"}
    )
    assert response.status_code == 302
    case = Case.objects.get(pk=case.pk)
    assert case.status == "open" and case.stage == "appeal"
    assert case.closing_reason == "" and case.closed_on is None
    titles = list(case.events.values_list("title", flat=True))
    assert any(t.startswith("Dosya kapatıldı") for t in titles)
    assert any(t.startswith("Dosya yeniden açıldı") for t in titles)


def test_decision_number_needs_year_and_sequence(case_factory):
    case = case_factory(case_type="civil")
    form = CaseCloseForm(_close_data(case, decision_sequence="7"), case=case)
    assert not form.is_valid() and "decision_year" in form.errors
    form = CaseCloseForm(_close_data(case, decision_year="2026"), case=case)
    assert form.is_valid() and form.cleaned_data["decision_no"] == ""
    form = CaseCloseForm(_close_data(case, decision_year="2026", decision_sequence="7"), case=case)
    assert form.is_valid() and form.cleaned_data["decision_no"] == "2026/7"


def test_lawyer_can_have_reviewer_and_task_form_suggests_it(admin_user, lawyer):
    from apps.accounts.forms import UserAdminForm
    from apps.tasks.forms import TaskForm

    form = UserAdminForm(
        {
            "first_name": lawyer.first_name or "Ayşe",
            "last_name": lawyer.last_name or "Deneme",
            "role": "lawyer",
            "supervisor": admin_user.pk,
            "order": lawyer.order,
            "is_active": "on",
        },
        instance=lawyer,
        editor=admin_user,
    )
    assert form.is_valid(), form.errors
    form.save()
    lawyer.refresh_from_db()
    assert lawyer.supervisor == admin_user
    assert TaskForm().supervisor_map[lawyer.pk] == admin_user.pk
