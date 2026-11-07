import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.tasks.models import PetitionSample

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\nornek dilekce"


def login(user):
    client = Client()
    client.force_login(user)
    return client


def person(role, name="kisi"):
    return User.objects.create_user(username=f"{name}-{role}", role=role)


def add(user, title="Cevap dilekçesi", petition_type="Cevap", description="", name="cevap.pdf"):
    sample = PetitionSample(
        title=title, petition_type=petition_type, description=description, created_by=user
    )
    sample.file.save(name, SimpleUploadedFile(name, PDF), save=False)
    sample.original_name = name
    sample.size = len(PDF)
    sample.save()
    return sample


# ---- erişim ----------------------------------------------------------------------------


def test_pool_requires_login():
    assert Client().get(reverse("tasks:pool")).status_code == 302


@pytest.mark.parametrize("role", list(User.Role))
def test_every_role_can_view_and_download(role, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    uploader = person(User.Role.LAWYER, "yukleyen")
    sample = add(uploader)
    viewer = person(role, "izleyen")
    client = login(viewer)
    html = client.get(reverse("tasks:pool")).content.decode()
    assert "Cevap dilekçesi" in html
    response = client.get(sample.file.url)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF


def test_pool_file_is_not_served_to_anonymous_users(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sample = add(person(User.Role.LAWYER))
    assert Client().get(sample.file.url).status_code == 302


def test_unknown_pool_file_is_not_found(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    (tmp_path / "petition-pool").mkdir()
    (tmp_path / "petition-pool" / "sahipsiz.pdf").write_bytes(PDF)
    client = login(person(User.Role.LAWYER))
    assert client.get("/media/petition-pool/sahipsiz.pdf").status_code == 404


# ---- yükleme -----------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(User.Role))
def test_everyone_can_upload(role, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = person(role)
    response = login(user).post(
        reverse("tasks:pool_create"),
        {
            "title": "İstinaf dilekçesi",
            "petition_type": "İstinaf",
            "description": "Ceza dosyaları için örnek",
            "file": SimpleUploadedFile("istinaf.pdf", PDF),
        },
    )
    assert response.status_code == 302
    sample = PetitionSample.objects.get()
    assert sample.created_by == user
    assert sample.original_name == "istinaf.pdf" and sample.size == len(PDF)
    assert sample.petition_type == "İstinaf"


def test_title_and_file_are_required(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    response = login(person(User.Role.LAWYER)).post(reverse("tasks:pool_create"), {"title": ""})
    assert {"title", "file"} <= set(response.context["form"].errors)
    assert not PetitionSample.objects.exists()


def test_unsupported_or_mismatched_files_are_rejected(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client = login(person(User.Role.LAWYER))
    exe = client.post(
        reverse("tasks:pool_create"),
        {"title": "Zararlı", "file": SimpleUploadedFile("a.exe", b"MZ")},
    )
    fake = client.post(
        reverse("tasks:pool_create"),
        {"title": "Sahte", "file": SimpleUploadedFile("a.pdf", b"bu pdf degil")},
    )
    assert "file" in exe.context["form"].errors and "file" in fake.context["form"].errors
    assert not PetitionSample.objects.exists()


def test_create_in_modal_frame_reloads_parent(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    response = login(person(User.Role.LAWYER)).post(
        reverse("tasks:pool_create") + "?pencere=1",
        {"title": "Pop-up", "file": SimpleUploadedFile("p.pdf", PDF)},
    )
    assert response.status_code == 200
    assert "window.parent.location.reload()" in response.content.decode()
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert PetitionSample.objects.count() == 1


# ---- arama, süzme, sayfalama ----------------------------------------------------------------


def titles(response):
    return [s.title for s in response.context["page_obj"].object_list]


def test_search_filters_by_title_description_and_type(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = person(User.Role.LAWYER)
    add(user, "Cevap dilekçesi", "Cevap", "alacak davası")
    add(user, "İstinaf başvurusu", "İstinaf", "ceza dosyası", name="i.pdf")
    client = login(user)
    assert titles(client.get(reverse("tasks:pool"), {"q": "istinaf"})) == ["İstinaf başvurusu"]
    assert titles(client.get(reverse("tasks:pool"), {"q": "alacak"})) == ["Cevap dilekçesi"]


def test_filter_by_type_and_type_choices(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = person(User.Role.LAWYER)
    add(user, "A", "Cevap")
    add(user, "B", "İstinaf", name="b.pdf")
    add(user, "C", "Cevap", name="c.pdf")
    response = login(user).get(reverse("tasks:pool"), {"tur": "Cevap"})
    assert sorted(titles(response)) == ["A", "C"]
    assert [(t["name"], t["count"]) for t in response.context["types"]] == [
        ("Cevap", 2),
        ("İstinaf", 1),
    ]


def test_newest_first_and_pagination(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = person(User.Role.LAWYER)
    for index in range(55):
        add(user, f"Dilekçe {index:02d}", name=f"d{index}.pdf")
    client = login(user)
    first = client.get(reverse("tasks:pool"))
    assert len(first.context["page_obj"].object_list) == 50
    assert titles(first)[0] == "Dilekçe 54"
    assert len(client.get(reverse("tasks:pool"), {"page": 2}).context["page_obj"].object_list) == 5


def test_htmx_request_returns_only_the_table(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = person(User.Role.LAWYER)
    add(user)
    response = login(user).get(reverse("tasks:pool"), HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert "Cevap dilekçesi" in html and "<html" not in html


# ---- silme ----------------------------------------------------------------------------------


def test_uploader_can_delete_and_file_is_removed(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    user = person(User.Role.INTERN)
    sample = add(user)
    path = sample.file.path
    assert login(user).post(reverse("tasks:pool_delete", args=[sample.pk])).status_code == 302
    assert not PetitionSample.objects.exists()
    assert not os.path.exists(path)


def test_admin_can_delete_anyones_sample(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sample = add(person(User.Role.LAWYER))
    admin = person(User.Role.ADMIN, "yonetici")
    assert login(admin).post(reverse("tasks:pool_delete", args=[sample.pk])).status_code == 302
    assert not PetitionSample.objects.exists()


def test_other_users_cannot_delete(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sample = add(person(User.Role.LAWYER))
    stranger = person(User.Role.SECRETARY, "baska")
    assert login(stranger).post(reverse("tasks:pool_delete", args=[sample.pk])).status_code == 403
    assert PetitionSample.objects.count() == 1


def test_delete_requires_post(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sample = add(person(User.Role.LAWYER))
    admin = person(User.Role.ADMIN, "y")
    assert login(admin).get(reverse("tasks:pool_delete", args=[sample.pk])).status_code == 405


# ---- menü -----------------------------------------------------------------------------------


def test_sidebar_links_to_pool_and_tasks_menu_stays_inactive_there(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client = login(person(User.Role.LAWYER))
    html = client.get(reverse("tasks:pool")).content.decode()
    assert reverse("tasks:pool") in html and "Dilekçe havuzu" in html
    tasks_link = html.split(f'href="{reverse("tasks:list")}"')[0].rsplit("<a", 1)[1]
    assert "active" not in tasks_link
