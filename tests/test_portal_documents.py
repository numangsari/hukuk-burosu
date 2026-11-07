import base64
import datetime as dt
import json

import pytest
from django.core.files.base import ContentFile
from django.test import Client

from apps.accounts.models import User
from apps.cases.models import Document, DocumentCategory
from apps.imports.models import PortalCase, PortalDocument, PortalLawyerAccess
from apps.imports.portal_ingest import parse_uyap_date

pytestmark = pytest.mark.django_db

INGEST = "/portal-inceleme/eklentiden-al/"
PDF = b"%PDF-1.4\nornek evrak"


@pytest.fixture
def setup(case_factory, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    lawyer = User.objects.create_user(username="evrak-avukat", role=User.Role.LAWYER)
    PortalLawyerAccess.objects.create(
        user=lawyer, identity_number="10000000146", uyap_enabled=True, uets_enabled=True
    )
    admin = User.objects.create_user(username="evrak-yonetici", role=User.Role.ADMIN)
    client = Client()
    client.force_login(admin)
    key = client.post("/portal-inceleme/baglanti/").context["pair_key"]
    case = case_factory()
    portal = PortalCase.objects.create(
        fingerprint="evrak-dosya-1",
        authority="Örnek Mahkeme",
        number="2026/1",
        data={"liste": {"dosyaId": "D1"}},
        case=case,
        source_unknown=False,
    )
    portal.source_users.add(lawyer)
    return Client(), {"HTTP_AUTHORIZATION": f"Bearer {key}"}, lawyer, case, portal


def body(**values):
    data = {
        "type": "uyap_document",
        "identity": "10000000146",
        "dosyaId": "D1",
        "evrakId": "E1",
        "meta": {"tur": "Tensip Zaptı", "tip": "DOSYA", "onaylandigiTarih": "05.11.2026"},
        "name": "tensip.pdf",
        "content": base64.b64encode(PDF).decode(),
    }
    data.update(values)
    return json.dumps(data)


def post(client, auth, payload):
    return client.post(INGEST, payload, content_type="application/json", **auth)


def test_document_is_stored_on_case_with_category_and_title(setup):
    client, auth, _, case, portal = setup
    response = post(client, auth, body())
    assert response.status_code == 200
    stored = PortalDocument.objects.get()
    assert stored.portal_case == portal and stored.evrak_id == "E1"
    document = Document.objects.get(case=case)
    assert stored.document == document
    assert "Tensip Zaptı" in document.title
    assert document.original_name.endswith(".pdf")
    assert document.file.read() == PDF


@pytest.mark.parametrize(
    ("tur", "category"),
    [
        ("Tebliğ Mazbatası", DocumentCategory.SERVICE),
        ("Karar", DocumentCategory.DECISION),
        ("Dilekçe", DocumentCategory.PETITION),
        ("Bilirkişi Raporu", DocumentCategory.EXPERT),
        ("Reddiyat Makbuzu", DocumentCategory.OTHER),
    ],
)
def test_category_follows_document_type(setup, tur, category):
    client, auth, _, case, _ = setup
    post(client, auth, body(meta={"tur": tur}))
    assert Document.objects.get(case=case).category == category


def test_same_evrak_is_not_stored_twice(setup):
    client, auth, _, case, _ = setup
    assert post(client, auth, body()).status_code == 200
    assert post(client, auth, body()).status_code == 200
    assert PortalDocument.objects.count() == 1
    assert Document.objects.filter(case=case).count() == 1


def test_deleted_case_document_is_not_downloaded_again(setup):
    client, auth, _, case, _ = setup
    post(client, auth, body())
    Document.objects.filter(case=case).delete()
    assert post(client, auth, body()).status_code == 200
    assert Document.objects.filter(case=case).count() == 0


def test_two_evraks_make_two_documents(setup):
    client, auth, _, case, _ = setup
    post(client, auth, body(evrakId="E1"))
    post(client, auth, body(evrakId="E2", meta={"tur": "Karar"}))
    assert Document.objects.filter(case=case).count() == 2


def test_case_not_yet_linked_returns_conflict_and_stores_nothing(setup):
    client, auth, _, _, portal = setup
    portal.case = None
    portal.save()
    response = post(client, auth, body())
    assert response.status_code == 409
    assert not PortalDocument.objects.exists()


def test_unknown_dosya_id_returns_not_found(setup):
    client, auth, *_ = setup
    assert post(client, auth, body(dosyaId="YOK")).status_code == 404


def test_other_lawyers_case_cannot_receive_documents(setup):
    client, auth, _, _, portal = setup
    stranger = User.objects.create_user(username="baska", role=User.Role.LAWYER)
    portal.source_users.set([stranger])
    assert post(client, auth, body()).status_code == 403
    assert not PortalDocument.objects.exists()


@pytest.mark.parametrize(
    "values",
    [
        {"evrakId": ""},
        {"evrakId": "x" * 257},
        {"dosyaId": "x" * 257},
        {"content": ""},
        {"content": "%%%geçersiz%%%"},
        {"name": 5},
        {"meta": "yok"},
        {"dosyaId": 7},
    ],
)
def test_invalid_payload_is_rejected(setup, values):
    client, auth, *_ = setup
    assert post(client, auth, body(**values)).status_code == 400
    assert not PortalDocument.objects.exists()


def test_oversized_document_is_rejected(setup):
    client, auth, *_ = setup
    big = base64.b64encode(b"%PDF-" + b"0" * 20_000_001).decode()
    assert post(client, auth, body(content=big)).status_code == 400


def test_unsafe_file_type_is_not_kept_with_executable_extension(setup):
    client, auth, _, case, _ = setup
    payload = body(name="virus.exe", content=base64.b64encode(b"MZ\x90 ornek").decode())
    assert post(client, auth, payload).status_code == 200
    assert Document.objects.get(case=case).original_name.endswith(".bin")


def test_unpermitted_identity_is_rejected(setup):
    client, auth, *_ = setup
    assert post(client, auth, body(identity="10000000147")).status_code == 403


def test_document_is_copied_into_office_folder_when_configured(setup, settings, tmp_path):
    from apps.office.models import OfficeSettings

    client, auth, _, case, _ = setup
    root = tmp_path / "ofis"
    root.mkdir()
    office = OfficeSettings.load()
    office.documents_root = str(root)
    office.save()
    assert post(client, auth, body()).status_code == 200
    copies = list(root.rglob("*.pdf"))
    assert len(copies) == 1
    assert "UYAP Evrakları" in str(copies[0])
    assert Document.objects.get(case=case).folder_path == str(copies[0])


def test_enforcement_account_capture_is_accepted(setup):
    # İcra dosyaları için eklenti `/dosya_hesap_bilgileri.ajx` yanıtı da gönderir.
    client, auth, _, _, portal = setup
    payload = json.dumps(
        {
            "type": "uyap",
            "identity": "10000000146",
            "captures": [
                {
                    "source": "UYAP",
                    "path": "/search_phrase_detayli.ajx",
                    "data": {
                        "kategori": "İcra",
                        "durum": "acik",
                        "sonuc": [
                            [{"dosyaId": "D1", "birimAdi": "Örnek İcra", "dosyaNo": "2026/9"}],
                            1,
                        ],
                    },
                },
                {
                    "source": "UYAP",
                    "path": "/dosya_hesap_bilgileri.ajx",
                    "data": {"kategori": "İcra", "dosyaId": "D1", "sonuc": {"ornek": True}},
                },
            ],
        }
    )
    assert post(client, auth, payload).status_code == 200


def test_real_world_66_character_ids_are_accepted(setup):
    # UYAP kimlikleri 66 karakter uzunluğundadır.
    client, auth, _, case, portal = setup
    long_dosya = "A" * 66
    portal.data = {"liste": {"dosyaId": long_dosya}}
    portal.save()
    response = post(client, auth, body(dosyaId=long_dosya, evrakId="B" * 66))
    assert response.status_code == 200
    stored = PortalDocument.objects.get()
    assert stored.evrak_id == "B" * 66
    assert Document.objects.filter(case=case).count() == 1


def test_note_shows_unit_number_but_not_the_long_internal_id(setup):
    client, auth, _, case, _ = setup
    post(client, auth, body(evrakId="Q" * 66, meta={"tur": "Karar", "birimEvrakNo": "11"}))
    document = Document.objects.get(case=case)
    assert document.notes == "UYAP evrakı · Birim evrak no: 11"
    assert "Q" * 66 not in document.notes


def test_note_without_unit_number_is_plain(setup):
    client, auth, _, case, _ = setup
    post(client, auth, body(meta={"tur": "Karar"}))
    assert Document.objects.get(case=case).notes == "UYAP evrakı"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14/10/2026", dt.date(2026, 10, 14)),
        ("05.11.2026", dt.date(2026, 11, 5)),
        ("2026-11-05", dt.date(2026, 11, 5)),
        ("14/10/2026 10:20", dt.date(2026, 10, 14)),
        ("", None),
        (None, None),
        ("dün", None),
        ("31/02/2026", None),
    ],
)
def test_uyap_date_parsing(raw, expected):
    assert parse_uyap_date(raw) == expected


def test_document_date_is_saved_from_uyap_date(setup):
    client, auth, _, case, _ = setup
    post(client, auth, body(meta={"tur": "Karar", "onaylandigiTarih": "14/10/2026"}))
    assert Document.objects.get(case=case).document_date == dt.date(2026, 10, 14)


def test_document_date_is_empty_when_uyap_date_is_unreadable(setup):
    client, auth, _, case, _ = setup
    post(client, auth, body(meta={"tur": "Karar", "onaylandigiTarih": "bilinmiyor"}))
    assert Document.objects.get(case=case).document_date is None


def test_documents_tab_sorts_and_shows_uyap_date(setup):
    from apps.accounts.models import User as UserModel

    _, _, _, case, _ = setup

    def make(title, name, **values):
        document = Document(case=case, title=title, original_name=name, **values)
        document.file.save(name, ContentFile(PDF), save=False)
        document.save()
        return document

    old_upload_new_date = make("Yeni tarihli", "a.pdf", document_date=dt.date(2026, 10, 20))
    new_upload_old_date = make("Eski tarihli", "b.pdf", document_date=dt.date(2025, 1, 5))
    manual = make("Elle yüklenen", "c.pdf")
    assert old_upload_new_date.pk < new_upload_old_date.pk < manual.pk
    admin = UserModel.objects.create_user(username="belge-yonetici", role=UserModel.Role.ADMIN)
    viewer = Client()
    viewer.force_login(admin)
    response = viewer.get(case.get_absolute_url())
    html = response.content.decode()
    # Elle yüklenen bugünün tarihiyle en üstte; sonra UYAP tarihine göre yeniden eskiye.
    assert html.index("Elle yüklenen") < html.index("Yeni tarihli") < html.index("Eski tarihli")
    assert "20.10.2026" in html and "05.01.2025" in html
