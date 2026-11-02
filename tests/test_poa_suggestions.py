import unicodedata

import pytest
from django.core.exceptions import ValidationError
from openpyxl import Workbook

from apps.accounts.models import User
from apps.clients.models import Client
from apps.imports.models import PowerOfAttorneyReview
from apps.imports.poa_review import SourceRow, read_source
from apps.imports.poa_suggestions import build_plan, execute, suggest

pytestmark = pytest.mark.django_db


@pytest.fixture
def source_and_teams(tmp_path, settings):
    path = tmp_path / "ornek.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["SIRA NO", "İSİM", "NOT"])
    for row in [
        ("V-001", "MELİS BAHAR", ""),
        ("V-002", "ÖRNEK TEKSTİL", ""),
        ("V-003", "NESLİHAN DEMİR BOŞANMA", "ASLI YOK"),
        ("V-004", "DENİZ KAYA", ""),
        ("V-005", "DENİZ KAYA", ""),
        ("V-006", "NİL YÖNETİCİLİĞİ", ""),
        ("V-007", "ÖRNEK 54", ""),
        ("V-008", "MEHMET YILMAZ ÖRNEK", ""),
        ("V-009", "SELİM ERDEM", ""),
        ("V-010", "YENİ MÜVEKKİL", ""),
        ("V-011", "İKİNCİ KİŞİ", ""),
        ("V-011", "ÜÇÜNCÜ KİŞİ", ""),
    ]:
        sheet.append(list(row))
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


def test_suggestion_preserves_explanation_and_leaves_ambiguous_names():
    person = suggest(SourceRow(1, "V-1", "DENEME KİŞİ BOŞANMA", ""))
    assert (person.kind, person.first_name, person.last_name, person.annotation) == (
        "person",
        "DENEME",
        "KİŞİ",
        "BOŞANMA",
    )
    company = suggest(SourceRow(2, "V-2", "ÖRNEK TEKSTİL", ""))
    assert (company.kind, company.title) == ("company", "ÖRNEK TEKSTİL")
    multiple = suggest(SourceRow(2, "V-2", "AHMET EMRE DENEME", ""))
    assert (multiple.first_name, multiple.last_name) == ("AHMET EMRE", "DENEME")
    association = suggest(SourceRow(2, "V-2", "ÖRNEK YARDIM DERNEĞİ", ""))
    assert (association.kind, association.title) == ("company", "ÖRNEK YARDIM DERNEĞİ")
    trade = suggest(SourceRow(2, "V-2", "ÖRNEK OTOMOTİV YEDEK PAR. TİC.", ""))
    assert (trade.kind, trade.title) == ("company", "ÖRNEK OTOMOTİV YEDEK PAR. TİC.")
    assert suggest(SourceRow(2, "V-2", "ÖRNEK OTOMOTİV, BAŞKA KİŞİ", "")) is None
    for value in ("AYŞE VE ALİ", "BAHAR YÖNETİCİLİĞİ", "BİR İKİ ÜÇ", "İKİ, KİŞİ", "HEDEF 54"):
        assert suggest(SourceRow(3, "V-3", value, "")) is None
    assert suggest(SourceRow(4, "", "ÖRNEK KİŞİ", "")) is None
    spaced = suggest(SourceRow(5, "V - 7", unicodedata.normalize("NFD", "ÖRNEK ÇİFTÇİ"), ""))
    assert spaced.row.poa_no == 7
    assert spaced.name == "ÖRNEK ÇİFTÇİ"


def test_automatic_import_skips_duplicates_and_preserves_notes(source_and_teams, admin_user):
    _, teams = source_and_teams
    existing = Client.objects.create(
        kind="person",
        first_name="Selim",
        last_name="Erdem",
        poa_no=99,
        responsible_lawyer=teams[0][0],
        responsible_intern=teams[0][1],
    )
    reviewed = Client.objects.create(
        kind="person",
        first_name="Başka",
        last_name="Kişi",
        poa_no=100,
        responsible_lawyer=teams[1][0],
        responsible_intern=teams[1][1],
    )
    source_hash, rows = read_source()
    PowerOfAttorneyReview.objects.create(
        source_sha256=source_hash, source_row=11, client=reviewed, created_by=admin_user
    )
    plan = build_plan(source_hash, rows)
    assert {item.row.number for item in plan} == {2, 3, 4}
    assert execute(source_hash) == 3
    assert Client.objects.count() == 5
    assert Client.objects.get(poa_no=2).kind == "company"
    annotated = Client.objects.get(poa_no=3)
    assert annotated.name == "NESLİHAN DEMİR"
    assert "BOŞANMA" in annotated.notes and "ASLI YOK" in annotated.notes
    linked = PowerOfAttorneyReview.objects.get(source_row=4)
    assert linked.client == annotated and linked.automatic and linked.created_by is None
    assert linked.source_reference == "V-003" and linked.source_note == "ASLI YOK"
    existing.refresh_from_db()
    assert existing.poa_no == 99
    assert execute(source_hash) == 0
    assert Client.objects.count() == 5


def test_automatic_import_does_not_run_on_changed_source(source_and_teams):
    with pytest.raises(ValidationError):
        execute("f" * 64)
    assert not Client.objects.exists()
    assert not PowerOfAttorneyReview.objects.exists()
