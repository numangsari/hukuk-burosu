import hashlib
import json

import pytest
from django.db import connection
from django.test import Client, override_settings

from apps.accounts.models import User
from apps.imports.models import (
    PortalCapture,
    PortalCase,
    PortalConnection,
    PortalLawyerAccess,
    PortalNotice,
)


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_import_records_account_owner(monkeypatch):
    monkeypatch.setitem(connection.settings_dict, "NAME", "ozkurt_deneme")
    monkeypatch.setitem(connection.settings_dict, "PORT", "5435")
    admin = User.objects.create_user(username="admin-owner", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(
        username="lawyer-owner", first_name="Örnek", last_name="Avukat"
    )
    PortalLawyerAccess.objects.create(user=lawyer, identity_number="10000000146", uets_enabled=True)
    key = "fake-ownership-key"
    PortalConnection.objects.create(owner=admin, key_hash=hashlib.sha256(key.encode()).hexdigest())
    response = Client().post(
        "/portal-inceleme/eklentiden-al/",
        json.dumps(
            {
                "type": "notice",
                "lawyer_name": "ÖRNEK AVUKAT",
                "list": {"id": "sample"},
                "details": {},
            }
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {key}",
    )
    assert response.status_code == 200
    notice = PortalNotice.objects.get()
    assert list(notice.source_users.all()) == [lawyer]
    assert not notice.source_unknown
    capture = PortalCapture.objects.get()
    assert list(capture.source_users.all()) == [lawyer]


@pytest.mark.django_db
def test_remove_permission_can_keep_data(client):
    admin = User.objects.create_user(username="remove-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="remove-lawyer")
    access = PortalLawyerAccess.objects.create(user=lawyer, identity_number="10000000146")
    notice = PortalNotice.objects.create(fingerprint="a" * 64, source_unknown=False)
    notice.source_users.add(lawyer)
    client.force_login(admin)
    page = client.get(f"/portal-inceleme/izin/{access.pk}/sil/")
    assert page.status_code == 200
    assert "Verileri de sil" in page.content.decode()
    response = client.post(f"/portal-inceleme/izin/{access.pk}/sil/", {"choice": "keep"})
    assert response.status_code == 302
    assert not PortalLawyerAccess.objects.filter(pk=access.pk).exists()
    assert notice.source_users.filter(pk=lawyer.pk).exists()


@pytest.mark.django_db
def test_remove_data_preserves_shared_and_unknown_records(client):
    admin = User.objects.create_user(username="delete-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="delete-lawyer")
    other = User.objects.create_user(username="other-lawyer")
    access = PortalLawyerAccess.objects.create(user=lawyer, identity_number="10000000146")
    exclusive = PortalNotice.objects.create(fingerprint="b" * 64, source_unknown=False)
    exclusive.source_users.add(lawyer)
    shared = PortalCase.objects.create(fingerprint="c" * 64, source_unknown=False)
    shared.source_users.add(lawyer, other)
    unknown = PortalCapture.objects.create(
        fingerprint="d" * 64, source="UYAP", path="/sample", data={}, source_unknown=True
    )
    unknown.source_users.add(lawyer)
    client.force_login(admin)
    response = client.post(f"/portal-inceleme/izin/{access.pk}/sil/", {"choice": "delete"})
    assert response.status_code == 302
    assert not PortalNotice.objects.filter(pk=exclusive.pk).exists()
    assert PortalCase.objects.filter(pk=shared.pk).exists()
    assert list(shared.source_users.all()) == [other]
    assert PortalCapture.objects.filter(pk=unknown.pk).exists()
    assert not unknown.source_users.filter(pk=lawyer.pk).exists()


@pytest.mark.django_db
def test_permission_removal_is_admin_only_and_requires_explicit_choice(client):
    lawyer = User.objects.create_user(username="no-admin")
    access = PortalLawyerAccess.objects.create(user=lawyer, identity_number="10000000146")
    client.force_login(lawyer)
    assert client.get(f"/portal-inceleme/izin/{access.pk}/sil/").status_code in (302, 403)
    assert client.post(
        f"/portal-inceleme/izin/{access.pk}/sil/", {"choice": "delete"}
    ).status_code in (302, 403)
    assert PortalLawyerAccess.objects.filter(pk=access.pk).exists()
    admin = User.objects.create_user(username="choice-admin", role=User.Role.ADMIN)
    client.force_login(admin)
    assert client.post(f"/portal-inceleme/izin/{access.pk}/sil/", {}).status_code == 404
    assert PortalLawyerAccess.objects.filter(pk=access.pk).exists()


@pytest.mark.django_db
def test_removing_owned_notice_removes_attached_source_documents(
    client, settings, tmp_path, django_capture_on_commit_callbacks
):
    from django.core.files.base import ContentFile

    from apps.imports.models import PortalNoticeDocument

    settings.MEDIA_ROOT = tmp_path
    admin = User.objects.create_user(username="document-admin", role=User.Role.ADMIN)
    lawyer = User.objects.create_user(username="document-lawyer")
    access = PortalLawyerAccess.objects.create(user=lawyer, identity_number="10000000146")
    notice = PortalNotice.objects.create(fingerprint="e" * 64, source_unknown=False)
    notice.source_users.add(lawyer)
    doc = PortalNoticeDocument(notice=notice, source_part="1", content_hash="f" * 64)
    doc.file.save("sample.pdf", ContentFile(b"sample"))
    path = tmp_path / doc.file.name
    assert path.exists()
    client.force_login(admin)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/portal-inceleme/izin/{access.pk}/sil/", {"choice": "delete"})
    assert response.status_code == 302
    assert not PortalNoticeDocument.objects.filter(pk=doc.pk).exists()
    assert not path.exists()
