import pytest
from django.urls import reverse

from apps.cases import decisions
from apps.cases.models import CaseEvent, CaseStep

pytestmark = pytest.mark.django_db


def _data(**kw):
    data = {
        "authority": "Sakarya Bölge Adliye Mahkemesi 2. Hukuk Dairesi",
        "official_year": "2026",
        "official_sequence": "310",
        "decision_date": "2026-10-20",
        "decision_year": "2026",
        "decision_sequence": "88",
        "decision": "reversed",
    }
    data.update(kw)
    return data


def test_decision_lists_cover_safahat_types():
    for case_type, items in decisions.DECISIONS.items():
        keys = [key for key, _ in items]
        assert len(keys) == len(set(keys)), case_type
        assert "other" in keys
    assert "consultancy" not in decisions.SAFAHAT_TYPES


def test_add_step_saves_numbers_and_redirects_to_safahat(lawyer_client, case_factory):
    case = case_factory(case_type="civil", authority="Eski Mahkeme", official_no="2025/10")
    url = reverse("cases:step_add", args=[case.pk])
    assert lawyer_client.get(url, HTTP_HX_REQUEST="true").status_code == 200
    response = lawyer_client.post(url, _data(), HTTP_HX_REQUEST="true")
    assert response.status_code == 204
    assert response["HX-Redirect"].endswith("#t-safahat")
    step = CaseStep.objects.get()
    assert step.official_no == "2026/310" and step.decision_no == "2026/88"
    assert step.authority == "SAKARYA BÖLGE ADLİYE MAHKEMESİ 2. HUKUK DAİRESİ"
    assert step.decision_label == "Bozma"
    case.refresh_from_db()
    assert case.authority == "ESKİ MAHKEME"  # güncelleme işaretlenmedi


def test_add_step_can_update_main_file(lawyer_client, case_factory):
    case = case_factory(case_type="civil", authority="Eski Mahkeme", official_no="2025/10")
    response = lawyer_client.post(
        reverse("cases:step_add", args=[case.pk]), _data(apply_to_case="on")
    )
    assert response.status_code == 302
    case.refresh_from_db()
    assert case.official_no == "2026/310" and case.authority.startswith("SAKARYA BÖLGE")
    event = case.events.get(kind=CaseEvent.Kind.STATUS)
    assert "Esas dosya bilgisi güncellendi" in event.title and "ESKİ MAHKEME" in event.description


def test_step_validation(lawyer_client, case_factory):
    case = case_factory(case_type="civil")
    url = reverse("cases:step_add", args=[case.pk])
    assert lawyer_client.post(url, _data(decision="")).status_code == 200
    assert lawyer_client.post(url, _data(decision="other")).status_code == 200
    assert lawyer_client.post(url, _data(decision_year="")).status_code == 200
    assert not CaseStep.objects.exists()
    assert lawyer_client.post(url, _data(decision="other", note="Açıklama")).status_code == 302
    assert CaseStep.objects.count() == 1


def test_apply_existing_step_and_edit(lawyer_client, case_factory):
    case = case_factory(case_type="administrative", authority="İdare Mahkemesi")
    step = CaseStep.objects.create(
        case=case, authority="Danıştay 10. Daire", official_no="2026/5", decision="upheld"
    )
    lawyer_client.post(reverse("cases:step_apply", args=[case.pk, step.pk]))
    case.refresh_from_db()
    assert case.authority == "DANIŞTAY 10. DAİRE" and case.official_no == "2026/5"
    edit = reverse("cases:step_edit", args=[case.pk, step.pk])
    assert lawyer_client.get(edit, HTTP_HX_REQUEST="true").status_code == 200
    lawyer_client.post(edit, _data(decision="reversed", authority="Danıştay 10. Daire"))
    step.refresh_from_db()
    assert step.decision == "reversed" and step.decision_no == "2026/88"


def test_step_not_available_for_consultancy_and_delete_is_admin_only(
    lawyer_client, admin_client_logged, case_factory
):
    consultancy = case_factory(case_type="consultancy", archive_no="C1")
    assert lawyer_client.get(reverse("cases:step_add", args=[consultancy.pk])).status_code == 404
    case = case_factory(case_type="civil", archive_no="C2")
    step = CaseStep.objects.create(case=case, authority="X", decision="upheld")
    delete = reverse("cases:step_delete", args=[case.pk, step.pk])
    # lawyer_client ve admin_client_logged aynı istemciyi paylaşır; son giriş yönetici olur.
    assert admin_client_logged.post(delete).status_code == 302
    assert not CaseStep.objects.exists()


def test_safahat_tab_lists_steps_in_order(lawyer_client, case_factory):
    case = case_factory(case_type="civil")
    CaseStep.objects.create(
        case=case, authority="İKİNCİ", decision="reversed", decision_date="2026-05-01"
    )
    CaseStep.objects.create(
        case=case, authority="BİRİNCİ", decision="upheld", decision_date="2026-02-01"
    )
    html = lawyer_client.get(case.get_absolute_url()).content.decode()
    html = html[html.index('id="t-safahat"') :]
    assert html.index("BİRİNCİ") < html.index("İKİNCİ")
    assert "Güncel esas dosya" in html
