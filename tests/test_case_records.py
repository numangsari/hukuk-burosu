import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agenda.services import system_events
from apps.cases.models import CaseEvent, Hearing

pytestmark = pytest.mark.django_db


def test_hearing_add_and_result_goes_to_timeline(lawyer_client, case_factory):
    case = case_factory(authority="İstanbul 3. Asliye Hukuk")
    r = lawyer_client.post(
        reverse("cases:hearing_add", args=[case.pk]),
        {
            "kind": "hearing",
            "starts_at": "2026-11-05T10:30",
            "authority": case.authority,
            "room": "12",
        },
    )
    assert r.status_code == 200
    h = Hearing.objects.get()
    assert timezone.localtime(h.starts_at).hour == 10
    lawyer_client.post(
        reverse("cases:hearing_result", args=[case.pk, h.pk]),
        {"status": "postponed", "result": "Tanık dinlenmesi için ertelendi"},
    )
    ev = CaseEvent.objects.get(case=case)
    assert ev.kind == "hearing" and "ertelendi" in ev.title and "Tanık" in ev.description


def test_timeline_note_delete_rights(lawyer_client, client, intern, case_factory):
    case = case_factory()
    lawyer_client.post(
        reverse("cases:event_add", args=[case.pk]),
        {"date": "2026-11-01", "title": "Müvekkil arandı"},
    )
    e = CaseEvent.objects.get()
    client.force_login(intern)
    client.post(reverse("cases:event_delete", args=[case.pk, e.pk]))
    assert CaseEvent.objects.exists()  # başkasının notunu silemez


def test_system_events_in_agenda(case_factory, lawyer):
    case = case_factory()
    today = timezone.localdate()
    start = timezone.make_aware(dt.datetime.combine(today + dt.timedelta(days=1), dt.time(9, 30)))
    Hearing.objects.create(case=case, starts_at=start, authority="Adliye")
    events = system_events(today, today + dt.timedelta(days=7))
    assert [e.source for e in events] == ["hearing"]


def test_case_detail_tabs_render(lawyer_client, case_factory):
    case = case_factory()
    html = lawyer_client.get(case.get_absolute_url()).content.decode()
    for label in ("Taraflar", "Görevler", "Duruşmalar", "Belgeler", "Geçmiş"):
        assert label in html
    assert "Tebligatlar" not in html and "Zaman çizelgesi" not in html
    assert "Safahat" in html  # varsayılan dosya türü hukuk davasıdır
