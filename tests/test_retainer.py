from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.clients.models import RetainerAgreement
from tests.conftest import client_form_data

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _post(client_http, owner, **row):
    data = client_form_data(
        owner,
        sozlesme=[{"signed_on": "2026-10-01", **row}],
    )
    return client_http.post(reverse("clients:update", args=[owner.pk]), data)


def test_retainer_agreement_saved_with_pdf_and_case(lawyer_client, client_factory, case_factory):
    owner = client_factory()
    case = case_factory(client=owner)
    pdf = SimpleUploadedFile("sozlesme.pdf", PDF, content_type="application/pdf")
    response = _post(lawyer_client, owner, case=case.pk, notes="İmzalı", **{"pdf": pdf})
    assert response.status_code == 302
    agreement = RetainerAgreement.objects.get()
    assert agreement.client == owner and agreement.case == case
    assert agreement.pdf.name.startswith(f"clients/{owner.pk}/sozlesme/")
    assert agreement.fee_amount is None


def test_retainer_case_must_belong_to_client(lawyer_client, client_factory, case_factory):
    owner = client_factory()
    other_case = case_factory(client=client_factory(first_name="Başka"))
    response = _post(lawyer_client, owner, case=other_case.pk)
    assert response.status_code == 200 and not RetainerAgreement.objects.exists()


def test_retainer_fee_suggests_accounting_entry(lawyer_client, client_factory, case_factory):
    owner = client_factory()
    case = case_factory(client=owner)
    response = _post(lawyer_client, owner, case=case.pk, fee_amount="25000")
    assert response.status_code == 302
    url = response["Location"]
    assert url.startswith(reverse("accounting:create"))
    assert "tur=fee" in url and "tutar=25000.00" in url and f"dosya={case.pk}" in url
    page = lawyer_client.get(url).content.decode()
    assert "25000" in page
    assert RetainerAgreement.objects.get().fee_amount == Decimal("25000")


def test_retainer_without_fee_goes_to_client_page(lawyer_client, client_factory):
    owner = client_factory()
    response = _post(lawyer_client, owner)
    assert response["Location"] == owner.get_absolute_url()
    page = lawyer_client.get(owner.get_absolute_url()).content.decode()
    assert "Avukatlık sözleşmeleri" in page and "01.10.2026" in page


def test_retainer_pdf_is_protected_and_served(lawyer_client, client_factory, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    owner = client_factory()
    pdf = SimpleUploadedFile("sozlesme.pdf", PDF, content_type="application/pdf")
    _post(lawyer_client, owner, pdf=pdf)
    agreement = RetainerAgreement.objects.get()
    response = lawyer_client.get(agreement.pdf.url)
    assert response.status_code == 200
    assert b"".join(response.streaming_content).startswith(b"%PDF")
