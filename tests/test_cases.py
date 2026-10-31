import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.cases.models import Case, CaseParty, Document
from apps.clients.models import Party

pytestmark = pytest.mark.django_db


def test_suggest_archive_no(case_factory):
    assert Case.suggest_archive_no() == "1"
    case_factory(archive_no="2026/0041")
    assert Case.suggest_archive_no() == "2026/0042"
    case_factory(archive_no="2026/0042-A")
    # Son kayıt "0042-A"; sıradaki "0043-A" önerilir.
    assert Case.suggest_archive_no() == "2026/0043-A"


def _case_data(client_obj, **kw):
    data = {
        "client": client_obj.pk,
        "case_type": "civil",
        "archive_no": "100",
        "subject": "Tazminat",
        "status": "pending",
        "stage": "first",
        "responsible_lawyer": client_obj.responsible_lawyer_id,
        "responsible_intern": client_obj.responsible_intern_id,
    }
    data.update(kw)
    return data


def test_create_case_and_archive_no_unique(lawyer_client, client_factory):
    c = client_factory()
    r = lawyer_client.post(reverse("cases:create"), _case_data(c))
    assert r.status_code == 302
    r = lawyer_client.post(reverse("cases:create"), _case_data(c, archive_no=" 100 "))
    assert r.status_code == 200
    assert "archive_no" in r.context["form"].errors


def test_type_specific_fields_cleared(lawyer_client, client_factory):
    c = client_factory()
    lawyer_client.post(
        reverse("cases:create"),
        _case_data(c, case_type="enforcement", enforcement_type="negotiable", crime="x"),
    )
    case = Case.objects.get()
    assert case.stage == ""  # icra takibinde aşama yok
    assert case.crime == ""
    assert case.enforcement_type == "negotiable"
    assert case.labels["official_no"] == "Takip No"


def test_create_prefills_from_client(lawyer_client, client_factory):
    c = client_factory()
    r = lawyer_client.get(reverse("cases:create"), {"client": c.pk})
    init = r.context["form"].initial
    assert init["responsible_lawyer"] == c.responsible_lawyer_id
    assert init["responsible_intern"] == c.responsible_intern_id


def test_case_list_default_hides_closed(lawyer_client, case_factory):
    case_factory(subject="Açık")
    case_factory(subject="Kapalı", status="closed")
    r = lawyer_client.get(reverse("cases:list"))
    assert [k.subject for k in r.context["cases"]] == ["Açık"]
    r = lawyer_client.get(reverse("cases:list"), {"status": "all"})
    assert len(r.context["cases"]) == 2


def test_party_add_reuses_identity_and_warns_on_client(lawyer_client, case_factory):
    case = case_factory()
    url = reverse("cases:party_add", args=[case.pk])
    lawyer_client.post(
        url, {"role": "defendant", "kind": "company", "name": "X A.Ş.", "identity_no": "1234567890"}
    )
    other = case_factory()
    lawyer_client.post(
        reverse("cases:party_add", args=[other.pk]),
        {"role": "debtor", "kind": "company", "name": "X Anonim", "identity_no": "1234567890"},
    )
    assert Party.objects.count() == 1
    assert CaseParty.objects.count() == 2

    # Müvekkil adıyla karşı taraf eklemek onay ister.
    r = lawyer_client.post(url, {"role": "defendant", "kind": "person", "name": case.client.name})
    assert case.client in r.context["conflicts"]
    assert CaseParty.objects.filter(case=case).count() == 1


def test_document_upload_and_delete_rights(
    lawyer_client, client, intern, case_factory, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    case = case_factory()
    f = SimpleUploadedFile("dilekçe örnek.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    lawyer_client.post(
        reverse("cases:document_upload", args=[case.pk]),
        {"title": "Dava dilekçesi", "category": "petition", "file": f},
    )
    doc = Document.objects.get()
    assert doc.original_name == "dilekçe örnek.pdf"
    assert doc.file.name.startswith(f"cases/{case.pk}/")

    client.force_login(intern)
    client.post(reverse("cases:document_delete", args=[case.pk, doc.pk]))
    assert Document.objects.exists()  # stajyer başkasının belgesini silemez


def test_detail_pages_render(lawyer_client, case_factory):
    case = case_factory()
    assert lawyer_client.get(case.get_absolute_url()).status_code == 200
    assert lawyer_client.get(case.client.get_absolute_url()).status_code == 200
    assert lawyer_client.get(reverse("core:home")).status_code == 200


def test_case_form_type_labels_are_json_object(lawyer_client):
    r = lawyer_client.get(reverse("cases:create"))
    # json_script ile tek seferde kodlanmış nesne olmalı (çift kodlanmış string değil)
    assert '<script id="type-labels" type="application/json">{"civil"' in r.content.decode()
