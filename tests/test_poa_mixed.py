import pytest
from django.urls import reverse
from openpyxl import Workbook

from apps.accounts.models import User
from apps.clients.models import Client, ClientContact
from apps.imports.models import PowerOfAttorneyReview, PowerOfAttorneyReviewMember
from apps.imports.poa_mixed import build_plan, execute, split_row
from apps.imports.poa_review import SourceRow, read_source

pytestmark = pytest.mark.django_db


@pytest.fixture
def mixed_source(tmp_path, settings):
    path = tmp_path / "ornek.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["SIRA NO", "İSİM", "NOT"])
    for values in [
        ("V-001", "ALİ ÖRNEK, DENEME GIDA TİC. LTD. ŞTİ.", ""),
        ("V-002", "ÖRNEK ŞİRKET A.Ş., MEHMET DENEME", ""),
        ("V-003", "BİRİNCİ TEKSTİL LTD. ŞTİ., İKİNCİ TİCARET A.Ş.", ""),
        ("V-004", "ESRA KAYA, ÖRNEK GÜVENLİK H,ZM. LTD. ŞTİ. (AZİL)", ""),
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
    _, rows = read_source()
    originals = [
        Client.objects.create(
            kind="company",
            title=row.name,
            poa_no=row.poa_no,
            responsible_lawyer=teams[0][0],
            responsible_intern=teams[0][1],
        )
        for row in rows
    ]
    return rows, originals, teams


def test_split_recognizes_mixed_order_and_preserves_internal_comma():
    entry = split_row(SourceRow(2, "V-1", "AYŞE ÖRNEK, DENEME GIDA H,ZM. LTD. ŞTİ.", ""))
    assert entry.company == "DENEME GIDA H,ZM. LTD. ŞTİ."
    assert (entry.other_kind, entry.other_first, entry.other_last) == ("person", "AYŞE", "ÖRNEK")
    reverse = split_row(SourceRow(3, "V-2", "DENEME TİC. A.Ş., ALİ ÖRNEK", ""))
    assert reverse.company == "DENEME TİC. A.Ş." and reverse.other_name == "ALİ ÖRNEK"
    companies = split_row(SourceRow(4, "V-3", "BİRİNCİ LTD. ŞTİ., İKİNCİ TİC. A.Ş.", ""))
    assert companies.other_kind == "company"
    assert split_row(SourceRow(5, "V-4", "AYŞE ÖRNEK, ALİ DENEME", "")) is None


def test_split_supports_spaced_dash_and_user_chosen_boundary():
    dashed = split_row(SourceRow(1, "V-1", "AYŞE ÖRNEK - DENEME GIDA LTD. ŞTİ.", ""))
    assert dashed.company == "DENEME GIDA LTD. ŞTİ."
    assert dashed.other_name == "AYŞE ÖRNEK"
    reverse = split_row(SourceRow(2, "V-2", "DENEME A.Ş. - ALİ ÖRNEK", ""))
    assert reverse.company == "DENEME A.Ş." and reverse.other_name == "ALİ ÖRNEK"
    unseparated = SourceRow(3, "V-3", "DENİZ KAYA A B C TEKSTİL LİMİTED ŞİRKETİ", "")
    assert split_row(unseparated) is None
    approved = split_row(unseparated, person_prefix_words=2)
    assert approved.other_name == "DENİZ KAYA"
    assert approved.company == "A B C TEKSTİL LİMİTED ŞİRKETİ"
    assert split_row(SourceRow(4, "V-4", "ALİ KAYA GIDA LTD. ŞTİ.", "")) is None
    assert split_row(unseparated, person_prefix_words=5) is None


def test_approved_unseparated_rows_are_split_without_touching_other_companies(tmp_path, settings):
    path = tmp_path / "ayrim.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["SIRA NO", "İSİM", "NOT"])
    values = [
        ("V-001", "AYŞE ÖRNEK - DENEME GIDA LTD. ŞTİ.", ""),
        ("V-002", "ALİ KAYA — İKİNCİ GIDA A.Ş.", ""),
        ("V-003", "DENİZ BAHAR A B C TEKSTİL LİMİTED ŞİRKETİ", ""),
        ("V-004", "GÜL YILMAZ ÖRNEK NAKLİYE LİMİTED ŞİRKETİ", ""),
        ("V-005", "SAMİ DENİZ YAPI DEKOR LİMİTED ŞİRKETİ", ""),
    ]
    for value in values:
        sheet.append(list(value))
    workbook.save(path)
    settings.POA_REVIEW_FILE = path
    settings.POA_REVIEW_TEAMS = (("test_lawyer_a", "test_intern_a"),)
    lawyer = User.objects.create_user(username="test_lawyer_a", role="lawyer")
    intern = User.objects.create_user(username="test_intern_a", role="intern")
    source_hash, rows = read_source()
    originals = [
        Client.objects.create(
            kind="company",
            title=row.name,
            poa_no=row.poa_no,
            responsible_lawyer=lawyer,
            responsible_intern=intern,
        )
        for row in rows
    ]
    assert len(build_plan(source_hash, rows)) == 2
    approvals = {rows[2].number: 2, rows[3].number: 2}
    assert len(build_plan(source_hash, rows, approved_splits=approvals)) == 4
    assert execute(source_hash, approved_splits=approvals) == (4, 4)
    originals[2].refresh_from_db()
    originals[3].refresh_from_db()
    originals[4].refresh_from_db()
    assert originals[2].name == "A B C TEKSTİL LİMİTED ŞİRKETİ"
    assert originals[3].name == "ÖRNEK NAKLİYE LİMİTED ŞİRKETİ"
    assert originals[4].name == rows[4].name
    assert Client.objects.get(name="DENİZ BAHAR").poa_no == 3
    assert Client.objects.get(name="GÜL YILMAZ").poa_no == 4
    assert execute(source_hash, approved_splits=approvals) == (0, 0)


def test_split_reuses_approved_client_and_keeps_both_numbers(mixed_source, admin_user, client):
    rows, originals, teams = mixed_source
    prior = Client.objects.create(
        kind="person",
        first_name="Ali",
        last_name="Örnek",
        poa_no=99,
        responsible_lawyer=teams[1][0],
        responsible_intern=teams[1][1],
    )
    source_hash, source = read_source()
    assert len(build_plan(source_hash, source)) == 3
    assert execute(source_hash, {rows[0].number: prior.pk}) == (4, 3)
    originals[0].refresh_from_db()
    prior.refresh_from_db()
    assert originals[0].name == "DENEME GIDA TİC. LTD. ŞTİ."
    assert prior.poa_no == 99 and prior.poa_labels == ["V-99", "V-1"]
    review = PowerOfAttorneyReview.objects.get(source_row=rows[0].number)
    assert review.client == originals[0] and review.members.get().client == prior
    assert review.expected_clients == 2
    assert Client.objects.get(name="MEHMET DENEME").poa_no == 2
    assert Client.objects.get(name="İKİNCİ TİCARET A.Ş.").poa_no == 3
    originals[3].refresh_from_db()
    assert originals[3].name == "ÖRNEK GÜVENLİK H,ZM. LTD. ŞTİ."
    assert "AZİL" in originals[3].notes
    assert "AZİL" in Client.objects.get(name="ESRA KAYA").notes
    client.force_login(admin_user)
    detail = client.get(reverse("clients:detail", args=[prior.pk]))
    assert "V-99" in detail.content.decode() and "V-1" in detail.content.decode()
    listing = client.get(reverse("clients:list"), {"q": "ali ornek"})
    assert "V-99" in listing.content.decode() and "V-1" in listing.content.decode()
    assert execute(source_hash, {rows[0].number: prior.pk}) == (0, 0)


def test_user_changed_or_related_combined_client_is_not_modified(mixed_source):
    rows, originals, _ = mixed_source
    originals[0].notes = "Kullanıcı notu"
    originals[0].save()
    ClientContact.objects.create(client=originals[1], kind="phone", value="0555 000 00 00")
    source_hash, source = read_source()
    assert {entry.row.number for entry, _, _ in build_plan(source_hash, source)} == {
        rows[2].number,
        rows[3].number,
    }
    execute(source_hash)
    originals[0].refresh_from_db()
    originals[1].refresh_from_db()
    assert originals[0].name == rows[0].name and originals[0].notes == "Kullanıcı notu"
    assert originals[1].name == rows[1].name and originals[1].contacts.count() == 1


def test_split_rolls_back_all_changes_on_failure(mixed_source, monkeypatch):
    rows, originals, _ = mixed_source
    source_hash, _ = read_source()

    def fail_member_creation(**kwargs):
        raise RuntimeError("Deneme hatası")

    monkeypatch.setattr(PowerOfAttorneyReviewMember.objects, "create", fail_member_creation)
    with pytest.raises(RuntimeError, match="Deneme hatası"):
        execute(source_hash)
    assert Client.objects.count() == len(originals)
    assert not PowerOfAttorneyReview.objects.exists()
    for row, original in zip(rows, originals, strict=True):
        original.refresh_from_db()
        assert original.name == row.name
