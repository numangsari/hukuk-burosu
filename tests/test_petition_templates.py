import io
import zipfile
from xml.etree import ElementTree

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.office.models import OfficeSettings, TaskType
from apps.tasks.petition_templates import fill_udf

pytestmark = pytest.mark.django_db


def sample_udf():
    text = "DAVACI : \nADRES : \nDAVALI : \nADRES : \nKONU : \n"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><template format_id="1.8"><content><![CDATA['
        + text
        + ']]></content><elements><paragraph><content startOffset="0" length="'
        + str(len(text))
        + '" /></paragraph></elements></template>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("content.xml", xml)
    return output.getvalue()


def text_from(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return ElementTree.fromstring(archive.read("content.xml")).find("content").text


def test_udf_preserves_unicode_and_fills_independent_fields():
    data = fill_udf(
        sample_udf(),
        {"davaci": "ÖRNEK KİŞİ", "davaci_adres": "ÖRNEK ADRES", "davali": "DİĞER KİŞİ"},
    )
    text = text_from(data)
    assert "DAVACI : ÖRNEK KİŞİ" in text
    assert "ADRES : ÖRNEK ADRES" in text
    assert "DAVALI : DİĞER KİŞİ" in text
    assert "KONU : \n" in text


def test_template_upload_admin_and_download(
    lawyer_client, admin_client, case_factory, client_factory, intern, lawyer, tmp_path
):
    from django.utils import timezone

    from apps.tasks.models import Task

    office = OfficeSettings.load()
    office.documents_root = str(tmp_path)
    office.save()
    task_type = TaskType.objects.get(name="Dava Dilekçesi Hazırlama Ve Dava Açılışı")
    upload_url = reverse("accounts:petition_templates")
    payload = {"task_type": task_type.pk, "template": SimpleUploadedFile("ornek.udf", sample_udf())}
    assert lawyer_client.post(upload_url, payload).status_code == 403
    payload["template"] = SimpleUploadedFile("ornek.udf", sample_udf())
    assert admin_client.post(upload_url, payload).status_code == 302
    task_type.refresh_from_db()
    assert (tmp_path / "Şablon Dilekçeler" / task_type.petition_template).is_file()
    person = client_factory(first_name="AŞIR", last_name="BOĞA")
    case = case_factory(
        client=person, authority="SAKARYA 3. ASLİYE HUKUK MAHKEMESİ", official_no="2025/454"
    )
    task = Task.objects.create(
        task_type=task_type,
        title="Örnek",
        case=case,
        assignee=intern,
        reviewer=lawyer,
        created_by=lawyer,
        due_date=timezone.localdate(),
    )
    response = lawyer_client.get(reverse("tasks:petition_template", args=[task.pk]))
    assert response.status_code == 200
    from apps.tasks.petition_templates import client_name

    assert client_name(task.client) in text_from(b"".join(response.streaming_content))
    from urllib.parse import unquote

    header = unquote(response["Content-Disposition"])
    assert (
        "Aşır BOĞA - Dava Dilekçesi - Sakarya 3. Asliye Hukuk Mahkemesi 2025-454 Esas.udf" in header
    )


def test_word_template_fills_names_split_across_formatting():
    from apps.tasks.petition_templates import fill_docx

    xml = b"""<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>DAV</w:t></w:r><w:r><w:t>ACI :</w:t></w:r></w:p><w:p><w:r><w:t>ADRES :</w:t></w:r></w:p></w:body></w:document>"""
    original = io.BytesIO()
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr("word/document.xml", xml)
        archive.writestr("word/styles.xml", b"<styles/>")
    output = fill_docx(original.getvalue(), {"davaci": "ÖRNEK KİŞİ", "davaci_adres": "ÖRNEK ADRES"})
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        xml = archive.read("word/document.xml").decode()
        assert "ÖRNEK KİŞİ" in xml and "ÖRNEK ADRES" in xml
        assert archive.read("word/styles.xml") == b"<styles/>"


def test_udf_rejects_missing_required_case_fields():
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        fill_udf(sample_udf(), {"davaci": "ÖRNEK"}, required={"mahkeme", "dosya_no"})


def test_turkish_person_names_and_company_titles(client_factory):
    from apps.clients.models import Party
    from apps.tasks.petition_templates import client_name, party_name

    person = client_factory(first_name="AŞIR İSMAİL", last_name="BOĞA ÇELİK")
    assert client_name(person) == "Aşır İsmail BOĞA ÇELİK"
    party = Party(kind="person", name="İSMAİL YILMAZ")
    assert party_name(party) == "İsmail YILMAZ"
    company = Party(kind="company", name="ÖRNEK GIDA A.Ş.")
    assert party_name(company) == "ÖRNEK GIDA A.Ş."
