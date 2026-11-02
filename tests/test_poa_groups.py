import pytest
from django.urls import reverse
from openpyxl import Workbook

from apps.accounts.models import User
from apps.clients.models import Client
from apps.imports.models import PowerOfAttorneyReview
from apps.imports.poa_groups import build_plan, execute
from apps.imports.poa_review import mark_processed, read_source

pytestmark = pytest.mark.django_db


@pytest.fixture
def grouped_source(tmp_path, settings):
    path = tmp_path / "vekalet.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["SIRA NO", "İSİM", "NOT"])
    for values in [
        ("V-001", "AYŞE BAHAR, MEHMET ERDEM", "ASLI YOK"),
        ("V-002", "DİLEK SARI, ELİF KAYA", ""),
        ("V-003", "MEVCUT KİŞİ, DİĞER KİŞİ", ""),
        ("V-004", "TEKRAR BİR, BİRİNCİ KİŞİ", ""),
        ("V-005", "TEKRAR BİR, İKİNCİ KİŞİ", ""),
        ("V-006", "KİŞİ VE KİŞİ, BAŞKA KİŞİ", ""),
    ]:
        sheet.append(list(values))
    workbook.save(path)
    settings.POA_REVIEW_FILE = path
    settings.POA_REVIEW_TEAMS = (
        ("test_lawyer_a", "test_intern_a"),
        ("test_lawyer_b", "test_intern_b"),
    )
    teams = []
    for suffix in ("a", "b"):
        lawyer = User.objects.create_user(username=f"test_lawyer_{suffix}", role="lawyer")
        intern = User.objects.create_user(username=f"test_intern_{suffix}", role="intern")
        teams.append((lawyer, intern))
    return path, teams


def test_groups_share_one_number_and_collisions_remain_pending(grouped_source):
    _, teams = grouped_source
    existing = Client.objects.create(
        kind="person",
        first_name="Mevcut",
        last_name="Kişi",
        poa_no=50,
        responsible_lawyer=teams[0][0],
        responsible_intern=teams[0][1],
    )
    source_hash, rows = read_source()
    groups = build_plan(source_hash, rows)
    assert {group.row.number for group in groups} == {2, 3}
    assert execute(source_hash) == (2, 4)
    assert Client.objects.filter(poa_no=1).count() == 2
    assert Client.objects.filter(poa_no=2).count() == 2
    review = PowerOfAttorneyReview.objects.get(source_row=2)
    assert review.expected_clients == 2
    assert review.members.count() == 1
    assert review.client.poa_no == review.members.get().client.poa_no == 1
    assert all("ASLI YOK" in c.notes for c in Client.objects.filter(poa_no=1))
    existing.refresh_from_db()
    assert existing.poa_no == 50
    _, new_rows = read_source()
    statuses = {row.number: row.status for row in mark_processed(source_hash, new_rows)}
    assert statuses[2] == statuses[3] == "done"
    assert statuses[4] == statuses[5] == statuses[6] == "pending"
    assert execute(source_hash) == (0, 0)


def test_incomplete_group_is_visible_and_can_be_repaired(grouped_source, client, admin_user):
    source_hash, _ = read_source()
    execute(source_hash)
    review = PowerOfAttorneyReview.objects.get(source_row=2)
    review.members.get().client.delete()
    _, rows = read_source()
    row = next(row for row in mark_processed(source_hash, rows) if row.number == 2)
    assert row.status == "incomplete"
    client.force_login(admin_user)
    url = reverse("imports:poa_review_detail", args=[2])
    detail = client.get(url)
    assert detail.status_code == 200 and detail.context["row"].status == "incomplete"
    response = client.post(
        url,
        {
            "source_hash": detail.context["source_hash"],
            "kind": "person",
            "first_name": "Mehmet",
            "last_name": "Erdem",
            "poa_no": "1",
            "title": "",
            "notes": "",
            "team": "auto",
        },
    )
    assert response.status_code == 302
    review.refresh_from_db()
    assert review.members.get().client.name == "MEHMET ERDEM"
    assert Client.objects.filter(poa_no=1).count() == 2
    _, rows = read_source()
    assert (
        next(row for row in mark_processed(source_hash, rows) if row.number == 2).status == "done"
    )


def test_group_import_rolls_back_if_any_client_fails(grouped_source, monkeypatch):
    source_hash, _ = read_source()
    original_save = Client.save
    calls = 0

    def fail_second_save(client, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Deneme hatası")
        return original_save(client, *args, **kwargs)

    monkeypatch.setattr(Client, "save", fail_second_save)
    with pytest.raises(RuntimeError, match="Deneme hatası"):
        execute(source_hash)
    assert not Client.objects.exists()
    assert not PowerOfAttorneyReview.objects.exists()
