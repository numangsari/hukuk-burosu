import pytest
from django.urls import reverse

from apps.cases.models import CaseEvent

pytestmark = pytest.mark.django_db


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


def test_case_detail_tabs_render(lawyer_client, case_factory):
    case = case_factory()
    html = lawyer_client.get(case.get_absolute_url()).content.decode()
    for label in ("Taraflar", "Görevler", "Belgeler", "Geçmiş"):
        assert label in html
    assert "Duruşmalar" not in html and "Sıradaki duruşma" not in html
    assert "Tebligatlar" not in html and "Zaman çizelgesi" not in html
    assert "Safahat" in html  # varsayılan dosya türü hukuk davasıdır
