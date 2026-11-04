import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from apps.accounts.models import User
from apps.cases.models import Case
from apps.clients.models import Client
from apps.imports.models import PortalCase, PortalLawyerAccess, PortalNotice, PortalNoticeDocument
from apps.office.models import OfficeSettings, TaskType
from apps.tasks.models import Task


@pytest.fixture
def sample(db, client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    admin = User.objects.create_user(username="notice-admin", role=User.Role.ADMIN)
    worker = User.objects.create_user(username="notice-worker", role=User.Role.LAWYER)
    owner = Client.objects.create(
        kind="company", title="Örnek kurum", responsible_lawyer=admin, responsible_intern=worker
    )
    other = Client.objects.create(
        kind="company", title="Diğer kurum", responsible_lawyer=admin, responsible_intern=worker
    )
    case = Case.objects.create(
        client=owner,
        case_type="civil",
        subject="Örnek",
        responsible_lawyer=admin,
        responsible_intern=worker,
    )
    notice = PortalNotice.objects.create(fingerprint="notice-example", subject="Örnek tebligat")
    doc = PortalNoticeDocument(
        notice=notice, source_part="part", content_hash="hash", original_name="belge.pdf"
    )
    doc.file.save("belge.pdf", ContentFile(b"%PDF-1.4\ndeneme"))
    client.force_login(admin)
    return client, admin, worker, owner, other, case, notice


@pytest.mark.django_db
def test_no_task_requires_reason_and_matching_case(sample):
    client, admin, worker, owner, other, case, notice = sample
    url = reverse("notice_no_task", args=[notice.pk])
    response = client.post(url, {"client": other.pk, "case": case.pk, "reason": "Gerek yok"})
    assert response.status_code == 200
    notice.refresh_from_db()
    assert notice.resolved_at is None
    response = client.post(url, {"client": owner.pk, "case": case.pk, "reason": ""})
    assert response.status_code == 200
    client.post(url, {"client": owner.pk, "case": case.pk, "reason": "Gerek yok"})
    notice.refresh_from_db()
    assert notice.resolution_client == owner and notice.resolution_case == case
    assert notice.no_task_reason == "Gerek yok" and notice.resolved_by == admin
    page = client.get(case.get_absolute_url()).content.decode()
    assert "Tebligat belgeleri" in page
    assert reverse("portal_notice_document", args=[notice.documents.get().pk]) in page
    client.post(url, {"client": other.pk, "reason": "Değişiklik"})
    notice.refresh_from_db()
    assert notice.no_task_reason == "Gerek yok"
    assert "Görev yok" in client.get(reverse("notice_list")).content.decode()


@pytest.mark.django_db
def test_notice_documents_are_copied_to_the_assigned_case(
    sample, tmp_path, django_capture_on_commit_callbacks
):
    client, _, _, owner, _, case, notice = sample
    office = OfficeSettings.load()
    office.documents_root = str(tmp_path / "ofis")
    office.save()
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("notice_no_task", args=[notice.pk]),
            {"client": owner.pk, "case": case.pk, "reason": "Gerek yok"},
        )
    assert response.status_code == 302
    from apps.imports.notice_folders import copy_notice_documents

    notice.refresh_from_db()
    assert copy_notice_documents(notice) == 1
    files = list((tmp_path / "ofis").rglob("Tebligatlar/*"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"%PDF-1.4\ndeneme"


@pytest.mark.django_db
def test_notice_copy_does_not_overwrite_existing_file(sample, tmp_path):
    from apps.core.folders import FolderError
    from apps.imports.notice_folders import copy_notice_documents

    _, _, _, owner, _, case, notice = sample
    office = OfficeSettings.load()
    office.documents_root = str(tmp_path / "ofis")
    office.save()
    notice.resolution_case = case
    notice.resolution_client = owner
    notice.save()
    copy_notice_documents(notice)
    target = next((tmp_path / "ofis").rglob("Tebligatlar/*"))
    target.write_bytes(b"korunacak")
    with pytest.raises(FolderError):
        copy_notice_documents(notice)
    assert target.read_bytes() == b"korunacak"


@pytest.mark.django_db
def test_notice_task_places_original_document_in_case_folder(
    sample, tmp_path, django_capture_on_commit_callbacks
):
    client, admin, worker, owner, _, case, notice = sample
    office = OfficeSettings.load()
    office.documents_root = str(tmp_path / "ofis")
    office.save()
    data = {
        "client": owner.pk,
        "case": case.pk,
        "task_type": TaskType.objects.filter(is_active=True).first().pk,
        "title": "İncele",
        "assignee": worker.pk,
        "reviewer": admin.pk,
        "due_date": "2026-12-01",
        "requires_accounting": "no",
    }
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("notice_task_create", args=[notice.pk]), data)
    assert response.status_code == 302
    files = list((tmp_path / "ofis").rglob("Tebligatlar/*"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"%PDF-1.4\ndeneme"


@pytest.mark.django_db
def test_notice_task_window_displays_accounting_choices(sample):
    client, _, _, _, _, _, notice = sample
    response = client.get(reverse("notice_task_create", args=[notice.pk]), HTTP_HX_REQUEST="true")
    page = response.content.decode()
    assert response.status_code == 200
    assert "data-notice-task" in page
    assert 'value="yes"' in page and 'value="no"' in page
    assert 'class="segment-choice"' in page
    assert "@change=" not in page


@pytest.mark.django_db
def test_notice_task_copies_documents_and_cannot_repeat(sample):
    client, admin, worker, owner, other, case, notice = sample
    kind = TaskType.objects.filter(is_active=True).first()
    url = reverse("notice_task_create", args=[notice.pk])
    data = {
        "client": owner.pk,
        "case": case.pk,
        "task_type": kind.pk,
        "title": "İncele",
        "assignee": worker.pk,
        "reviewer": admin.pk,
        "due_date": "2026-12-01",
        "requires_accounting": "no",
    }
    response = client.post(url, data)
    assert response.status_code == 302
    notice.refresh_from_db()
    assert notice.resolution_task is not None
    document = notice.resolution_task.documents.get()
    assert document.file.read() == b"%PDF-1.4\ndeneme"
    page = client.get(case.get_absolute_url()).content.decode()
    assert "Tebligat belgeleri" in page and "Görev belgeleri" in page
    assert reverse("portal_notice_document", args=[notice.documents.get().pk]) in page
    assert document.file.url in page
    client.post(url, data)
    assert Task.objects.count() == 1
    assert "Görev oluşturuldu" in client.get(reverse("notice_list")).content.decode()


@pytest.mark.django_db
def test_case_badges_and_portal_parties_are_read_only(client):
    admin = User.objects.create_user(username="badge-admin", role=User.Role.ADMIN)
    office_client = Client.objects.create(
        kind="company", title="Örnek", responsible_lawyer=admin, responsible_intern=admin
    )
    case = Case.objects.create(
        client=office_client,
        case_type="civil",
        subject="Örnek",
        responsible_lawyer=admin,
        responsible_intern=admin,
    )
    client.force_login(admin)
    page = client.get(case.get_absolute_url()).content.decode()
    assert "badge-source-office" in page
    assert 'aria-label="Ofis kaydı"' in page
    record = PortalCase.objects.create(
        fingerprint="badge-source",
        authority="Mahkeme",
        number="2026/1",
        case=case,
        data={"taraf_listeleri": [[{"adi": "KAYNAK TARAF", "rol": "Davacı"}]]},
    )
    page = client.get(case.get_absolute_url()).content.decode()
    assert "badge-source-uyap" in page
    assert 'aria-label="UYAP kaydı"' in page
    assert "KAYNAK TARAF" in page and "UYAP taraf bilgileri" in page
    assert record.case.client_id == office_client.pk
    listing = client.get(reverse("cases:list")).content.decode()
    assert "badge-source-uyap" in listing


@pytest.mark.django_db
def test_only_admin_manages_portal_access(client):
    admin = User.objects.create_user(username="access-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="access-lawyer", role=User.Role.LAWYER)
    url = reverse("accounts:settings")
    payload = {
        "section": "eklenti",
        "user": lawyer.pk,
        "identity_number": "10000000146",
        "uyap_enabled": "on",
    }
    client.force_login(lawyer)
    assert client.post(url, payload).status_code == 403
    assert PortalLawyerAccess.objects.count() == 0
    client.force_login(admin)
    assert client.post(url, payload).status_code == 302
    access = PortalLawyerAccess.objects.get(user=lawyer)
    assert access.uyap_enabled and not access.uets_enabled
    page = client.get(url + "?bolum=eklenti").content.decode()
    assert "hangi avukatın UYAP" in page
    assert "10000000146" not in page
    assert f"?bolum=eklenti&amp;izin={access.pk}#izin-formu" in page
    edit = client.get(url + f"?bolum=eklenti&izin={access.pk}").content.decode()
    assert "Kişi iznini düzenle" in edit
    payload.update({"access_id": access.pk, "uyap_enabled": "", "uets_enabled": "on"})
    assert client.post(url, payload).status_code == 302
    access.refresh_from_db()
    assert not access.uyap_enabled and access.uets_enabled


@pytest.mark.django_db
def test_missing_notice_document_prevents_task(sample):
    client, admin, worker, owner, other, case, notice = sample
    document = notice.documents.get()
    document.file.delete(save=False)
    kind = TaskType.objects.filter(is_active=True).first()
    response = client.post(
        reverse("notice_task_create", args=[notice.pk]),
        {
            "client": owner.pk,
            "case": case.pk,
            "task_type": kind.pk,
            "title": "İncele",
            "assignee": worker.pk,
            "reviewer": admin.pk,
            "due_date": "2026-12-01",
            "requires_accounting": "no",
        },
    )
    assert response.status_code == 200
    assert "belgesine erişilemedi" in response.content.decode()
    notice.refresh_from_db()
    assert notice.resolved_at is None and not Task.objects.exists()


@pytest.mark.django_db
def test_uyap_fields_appear_without_changing_office_fields(client):
    admin = User.objects.create_user(username="summary-admin", role=User.Role.ADMIN)
    owner = Client.objects.create(
        kind="company", title="Örnek", responsible_lawyer=admin, responsible_intern=admin
    )
    case = Case.objects.create(
        client=owner,
        case_type="civil",
        subject="Ofis konusu",
        responsible_lawyer=admin,
        responsible_intern=admin,
    )
    PortalCase.objects.create(
        fingerprint="source-summary",
        authority="Örnek Mahkeme",
        number="2026/5",
        case=case,
        data={
            "liste": {
                "dosyaDurum": "Açık",
                "dosyaAcilisTarihi": {"date": {"day": 3, "month": 4, "year": 2025}},
            },
            "ayrintilar": [
                {
                    "davaninKonusu": "Örnek kaynak konusu",
                    "kararNo": "2026/77",
                    "kararTarihi": "Apr 4, 2024 12:24:56 PM",
                },
                {"kararNo": "", "takibinYoluAciklama": "Örnek takip"},
            ],
            "hesaplar": [[{"textAlan": "Örnek alacak", "degerAlan": "1250"}]],
            "belge_listeleri": [
                {"son20Evrak": [{"tur": "Örnek karar", "aciklama": "Kaynak evrak"}]}
            ],
        },
    )
    client.force_login(admin)
    html = client.get(case.get_absolute_url()).content.decode()
    for value in (
        "UYAP bilgileri",
        "Örnek Mahkeme",
        "03.04.2025",
        "Örnek kaynak konusu",
        "2026/77",
        "04.04.2024",
        "Örnek takip",
        "Örnek alacak",
        "1250",
    ):
        assert value in html
    assert "UYAP evrak bilgileri" not in html
    assert "Kaynak evrak" not in html
    case.refresh_from_db()
    assert case.subject == "OFİS KONUSU" and case.client_id == owner.pk
    assert case.documents.count() == 0


@pytest.mark.django_db
def test_notice_due_date_uses_office_settings():
    import datetime as dt

    from apps.imports.portal_matching import calculate_notice_due_date
    from apps.office.models import OfficeSettings

    delivered = dt.date(2026, 11, 1)
    office = OfficeSettings.load()
    office.notice_default_due_days = 14
    office.save(update_fields=["notice_default_due_days"])
    assert calculate_notice_due_date(delivered) == dt.date(2026, 11, 15)

    office.notice_default_due_days = 7
    office.save(update_fields=["notice_default_due_days"])
    assert calculate_notice_due_date(delivered) == dt.date(2026, 11, 8)
