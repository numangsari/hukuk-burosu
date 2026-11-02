from pathlib import Path
from unittest.mock import patch

import pytest
from django.urls import reverse
from openpyxl import Workbook

from apps.accounts.models import User
from apps.clients.models import Client
from apps.imports.models import PowerOfAttorneyReview
from apps.imports.poa_review import read_source

pytestmark = pytest.mark.django_db


@pytest.fixture
def source_file(tmp_path, settings):
    path = tmp_path / "vek.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["SIRA NO", "İSİM", "Sütun1"])
    sheet.append(["V-001", "ÖRNEK ŞİRKET A.Ş.", "ASLI YOK"])
    sheet.append(["V-002", "AYŞE DENEME", ""])
    sheet.append(["V-003", "AYŞE DENEME", ""])
    sheet.append(["V-004", "BAŞKA KİŞİ", ""])
    workbook.save(path)
    settings.POA_REVIEW_FILE = path
    settings.POA_REVIEW_TEAMS = (
        ("test_lawyer_a", "test_intern_a"),
        ("test_lawyer_b", "test_intern_b"),
    )
    return path


@pytest.fixture
def review_teams(source_file):
    teams = []
    for suffix in ("a", "b"):
        lawyer = User.objects.create_user(username=f"test_lawyer_{suffix}", role="lawyer")
        intern = User.objects.create_user(username=f"test_intern_{suffix}", role="intern")
        teams.append((lawyer, intern))
    return teams


@pytest.fixture
def review_client(client, admin_user, review_teams):
    client.force_login(admin_user)
    return client


def make_client(team, **fields):
    return Client.objects.create(responsible_lawyer=team[0], responsible_intern=team[1], **fields)


def form_data(response, **changes):
    data = {
        "source_hash": response.context["source_hash"],
        "kind": "person",
        "first_name": "Ayşe",
        "last_name": "Deneme",
        "title": "",
        "poa_no": "2",
        "notes": "",
        "team": "auto",
    }
    data.update(changes)
    return data


def test_list_is_private_and_identifies_prior_imports(client, lawyer, admin_user, review_teams):
    prior = make_client(review_teams[0], kind="company", title="ÖRNEK ŞİRKET A.Ş.", poa_no=1)
    conflict = make_client(review_teams[0], kind="company", title="FARKLI A.Ş.", poa_no=4)
    client.force_login(lawyer)
    assert client.get(reverse("imports:poa_review")).status_code == 403
    client.force_login(admin_user)
    response = client.get(reverse("imports:poa_review"))
    assert response.status_code == 200
    assert response.context["pending"] == 3
    assert response.context["completed"] == 1
    rows = {row.number: row for row in response.context["rows"]}
    assert rows[5].status == "conflict" and rows[5].client_id == conflict.pk
    done = client.get(reverse("imports:poa_review"), {"durum": "done"})
    assert done.context["rows"][0].client_id == prior.pk
    search = client.get(reverse("imports:poa_review"), {"q": "ayse"}, HTTP_HX_REQUEST="true")
    assert search.status_code == 200 and len(search.context["rows"]) == 2


def test_user_chooses_and_saves_person_with_balanced_team(review_client, review_teams):
    make_client(review_teams[0], kind="company", title="DENEME A.Ş.", poa_no=10)
    url = reverse("imports:poa_review_detail", args=[3])
    detail = review_client.get(url)
    assert detail.status_code == 200
    assert detail.context["form"].initial.get("kind") is None
    assert Client.objects.count() == 1
    response = review_client.post(url, form_data(detail))
    assert response.status_code == 302
    created = Client.objects.get(poa_no=2)
    assert created.name == "AYŞE DENEME"
    assert created.responsible_lawyer == review_teams[1][0]
    assert created.responsible_intern == review_teams[1][1]
    assert PowerOfAttorneyReview.objects.get(source_row=3).client == created
    assert review_client.post(url, form_data(detail, poa_no="20")).status_code == 200
    assert Client.objects.count() == 2
    assert review_client.get(reverse("imports:poa_review")).context["pending"] == 3


def test_duplicate_name_needs_explicit_choice_and_can_link_existing(review_client, review_teams):
    existing = make_client(
        review_teams[0], kind="person", first_name="Ayşe", last_name="Deneme", poa_no=2
    )
    url = reverse("imports:poa_review_detail", args=[4])
    detail = review_client.get(url)
    assert existing in detail.context["matches"]
    failed = review_client.post(url, form_data(detail, poa_no="3"))
    assert failed.status_code == 200
    assert "Ayrı bir kişi" in str(failed.context["form"].non_field_errors())
    assert Client.objects.count() == 1
    response = review_client.post(
        url,
        {"action": "link", "source_hash": detail.context["source_hash"], "client_id": existing.pk},
    )
    assert response.status_code == 302
    existing.refresh_from_db()
    assert existing.poa_no == 2
    linked = PowerOfAttorneyReview.objects.get(source_row=4)
    assert linked.client == existing
    assert linked.source_reference == "V-003"
    client_detail = review_client.get(reverse("clients:detail", args=[existing.pk]))
    assert "V-003" in client_detail.content.decode()
    assert Client.objects.count() == 1


def test_conflicting_number_must_not_overwrite_existing_client(review_client, review_teams):
    existing = make_client(review_teams[0], kind="company", title="ÖRNEK TİCARET A.Ş.", poa_no=4)
    url = reverse("imports:poa_review_detail", args=[5])
    detail = review_client.get(url)
    assert detail.context["number_owner"] == existing
    failed = review_client.post(
        url, form_data(detail, first_name="Başka", last_name="Kişi", poa_no="4")
    )
    assert failed.status_code == 200
    assert "Paylaşıldığını doğrulayın" in str(failed.context["form"].non_field_errors())
    existing.refresh_from_db()
    assert existing.name == "ÖRNEK TİCARET A.Ş." and existing.poa_no == 4
    assert not PowerOfAttorneyReview.objects.exists()
    accepted = review_client.post(
        url,
        form_data(
            detail, first_name="Başka", last_name="Kişi", poa_no="4", confirm_shared_poa="on"
        ),
    )
    assert accepted.status_code == 302
    assert Client.objects.filter(poa_no=4).count() == 2
    existing.refresh_from_db()
    assert existing.name == "ÖRNEK TİCARET A.Ş." and existing.poa_no == 4


def test_zero_is_not_a_valid_poa_number(review_client):
    url = reverse("imports:poa_review_detail", args=[3])
    detail = review_client.get(url)
    result = review_client.post(url, form_data(detail, poa_no="0"))
    assert result.status_code == 200
    assert "poa_no" in result.context["form"].errors
    assert not Client.objects.exists()


def test_changed_or_missing_source_cannot_create_records(review_client, source_file, settings):
    url = reverse("imports:poa_review_detail", args=[3])
    detail = review_client.get(url)
    workbook = Workbook()
    workbook.active.append(["SIRA NO", "İSİM"])
    workbook.active.append(["V-002", "BAŞKA İSİM"])
    workbook.active.append(["V-003", "AYŞE DENEME"])
    workbook.save(source_file)
    response = review_client.post(url, form_data(detail))
    assert response.status_code == 200
    assert "liste değişmiş" in str(response.context["form"].non_field_errors())
    assert not Client.objects.exists()
    settings.POA_REVIEW_FILE = Path(source_file.parent / "olmayan.xlsx")
    missing = review_client.get(reverse("imports:poa_review"))
    assert missing.status_code == 200 and "bulunamadı" in missing.content.decode()


def test_company_review_preserves_source_note(review_client):
    url = reverse("imports:poa_review_detail", args=[2])
    detail = review_client.get(url)
    response = review_client.post(
        url,
        form_data(
            detail,
            kind="company",
            first_name="",
            last_name="",
            title="ÖRNEK ŞİRKET A.Ş.",
            poa_no="1",
            notes=detail.context["form"].initial["notes"],
        ),
    )
    assert response.status_code == 302
    created = Client.objects.get(poa_no=1)
    assert created.kind == "company"
    assert "ASLI YOK" in created.notes
    review = PowerOfAttorneyReview.objects.get(source_row=2)
    assert review.source_reference == "V-001" and review.source_note == "ASLI YOK"


def test_source_change_during_save_rolls_back(review_client):
    url = reverse("imports:poa_review_detail", args=[3])
    detail = review_client.get(url)
    source_hash, rows = read_source()
    with patch(
        "apps.imports.poa_review.read_source", side_effect=[(source_hash, rows), ("f" * 64, rows)]
    ):
        response = review_client.post(url, form_data(detail))
    assert response.status_code == 200
    assert "liste değişmiş" in str(response.context["form"].non_field_errors())
    assert not Client.objects.exists()
    assert not PowerOfAttorneyReview.objects.exists()


def test_unrelated_client_cannot_be_linked(review_client, review_teams):
    other = make_client(review_teams[0], kind="company", title="BAĞIMSIZ A.Ş.", poa_no=50)
    url = reverse("imports:poa_review_detail", args=[3])
    detail = review_client.get(url)
    response = review_client.post(
        url,
        {"action": "link", "source_hash": detail.context["source_hash"], "client_id": other.pk},
    )
    assert response.status_code == 302
    assert not PowerOfAttorneyReview.objects.exists()
