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
    assert 'id="t-tebligatlar"' not in html and "Zaman çizelgesi" not in html
    assert 'href="/tebligatlar/"' in html
    assert "Safahat" in html  # varsayılan dosya türü hukuk davasıdır


def test_notes_only_appear_at_bottom_of_summary(lawyer_client, case_factory, lawyer):
    case = case_factory(notes="Önceki dosya notu")
    event = CaseEvent.objects.create(
        case=case,
        date="2026-11-01",
        kind=CaseEvent.Kind.STATUS,
        title="Örnek otomatik olay",
        created_by=lawyer,
    )
    note = CaseEvent.objects.create(
        case=case,
        date="2026-11-01",
        kind=CaseEvent.Kind.NOTE,
        title="Örnek elle yazılan not",
        description="Örnek not açıklaması",
        created_by=lawyer,
    )
    html = lawyer_client.get(case.get_absolute_url()).content.decode()
    assert "Notlar ve olaylar" not in html and "Son hareketler" not in html
    assert event.title not in html
    assert html.index('id="case-notes"') > html.index(">Tarihler<")
    assert html.index('id="case-notes"') < html.index('id="t-taraflar"')
    note_section = html.split('id="case-notes"', 1)[1].split("<script>", 1)[0]
    assert case.notes in note_section and note.title in note_section
    history = html.split('id="t-gecmis"', 1)[1].split('id="t-muhasebe"', 1)[0]
    assert 'id="case-notes"' not in history
    assert CaseEvent.objects.filter(pk=event.pk).exists()
    response = lawyer_client.post(
        reverse("cases:event_add", args=[case.pk]),
        {"date": "2026-11-01", "title": "Yeni örnek not", "description": "Not metni"},
    )
    partial = response.content.decode()
    assert response.status_code == 200 and 'id="case-notes"' in partial
    assert "Yeni örnek not" in partial and event.title not in partial
    assert (
        lawyer_client.post(reverse("cases:event_delete", args=[case.pk, event.pk])).status_code
        == 404
    )
    assert CaseEvent.objects.filter(pk=event.pk).exists()
    assert (
        lawyer_client.post(reverse("cases:event_delete", args=[case.pk, note.pk])).status_code
        == 200
    )
    assert not CaseEvent.objects.filter(pk=note.pk).exists()
