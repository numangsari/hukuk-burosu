import pytest

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounts.models import User
from apps.cases.models import Case, CaseType
from apps.clients.models import Client
from apps.imports.models import PortalCase
from apps.imports.portal_finance import import_finance

BAKANLIK = "AİLE VE SOSYAL HİZMETLER BAKANLIĞI"


def make_case(case_type, client, role, lawyer):
    return Case.objects.create(
        client=client,
        case_type=case_type,
        client_role=role,
        responsible_lawyer=lawyer,
        responsible_intern=lawyer,
    )


def make_record(case, number, block, lawyer, category="İcra Dosyası"):
    record = PortalCase.objects.create(
        fingerprint=number.replace("/", "-").ljust(64, "f"),
        authority="Örnek Daire",
        number=number,
        category=category,
        case=case,
        data={"tahsilatlar": [block]},
    )
    record.source_users.add(lawyer)
    return record


def enforcement_block():
    """2026/33950 ekran görüntüsünden: borç tahsilatı, masraf avansı, PTT reddiyatı, harçlar."""
    return {
        "tahsilatList": [
            {
                "kayitId": 1,
                "makbuzNo": "198052",
                "odeyenKisi": "TEST TARAF",
                "tahsilatTuru": "Borç Tahsilatı",
                "tahsilatTarihi": "Jul 13, 2026 2:53:09 PM",
                "tahsilatTutari": 38268,
            },
            {
                "kayitId": 2,
                "makbuzNo": "174623",
                "odeyenKisi": BAKANLIK,
                "tahsilatTuru": "Masraf Avansı Tahsilatı",
                "tahsilatTarihi": "Jun 19, 2026 2:39:48 PM",
                "tahsilatTutari": 265,
            },
        ],
        "reddiyatList": [
            {
                "kayitId": 1,
                "makbuzNo": "224464",
                "odeyenKisi": BAKANLIK,
                "reddiyatNedeni": "Borç Reddiyatı",
                "reddiyatTarihi": "Jul 16, 2026 12:00:00 AM",
                "miktar": 38268,
                "tahsilHarci": 1218.03,
                "cezaeviHarcTutari": 535.40,
                "odenecekMiktar": 36514.57,
            },
            {
                "kayitId": 2,
                "makbuzNo": "198171",
                "odeyenKisi": "PTT",
                "reddiyatNedeni": "Posta Ücreti Reddiyatı",
                "reddiyatTarihi": "Jun 23, 2026 12:00:00 AM",
                "miktar": 265,
                "odenecekMiktar": 265,
            },
        ],
        "harcList": [
            {"odeyenKisi": BAKANLIK, "tahsilatTuru": "Başvurma Harcı", "miktar": 732},
            {"odeyenKisi": BAKANLIK, "tahsilatTuru": "Cezaevi Harcı (Nispi)", "miktar": 535.4},
            {"odeyenKisi": BAKANLIK, "tahsilatTuru": "Tahsil Harcı", "miktar": 1218.03},
            {"odeyenKisi": BAKANLIK, "tahsilatTuru": "Posta Masrafı", "miktar": 265},
        ],
    }


@pytest.fixture
def lawyer(db):
    return User.objects.create_user(
        username="fin-avukat", first_name="Test", last_name="Avukat", role=User.Role.LAWYER
    )


@pytest.fixture
def ministry(lawyer):
    return Client.objects.create(
        kind="company", title=BAKANLIK, responsible_lawyer=lawyer, responsible_intern=lawyer
    )


@pytest.mark.django_db
def test_enforcement_expense_and_net_debt_collection(lawyer, ministry):
    case = make_case(CaseType.ENFORCEMENT, ministry, "creditor", lawyer)
    record = make_record(case, "2026/33950", enforcement_block(), lawyer)
    result = import_finance(record)
    assert result["yazilan"] == 2
    entries = LedgerEntry.objects.filter(case=case)
    expense = entries.get(kind=EntryKind.EXPENSE)
    assert expense.amount == 265 and expense.date.isoformat() == "2026-06-19"
    income = entries.get(kind=EntryKind.TRUST_IN)
    assert str(income.amount) == "36514.57" and income.date.isoformat() == "2026-07-16"
    assert "kesinti 1753.43" in income.description
    assert import_finance(record)["yazilan"] == 0 and entries.count() == 2


@pytest.mark.django_db
def test_debt_collection_not_written_when_client_is_debtor_or_unpaid(lawyer, ministry):
    case = make_case(CaseType.ENFORCEMENT, ministry, "debtor", lawyer)
    record = make_record(case, "2026/1", enforcement_block(), lawyer)
    import_finance(record)
    assert not LedgerEntry.objects.filter(kind=EntryKind.TRUST_IN).exists()
    assert LedgerEntry.objects.filter(kind=EntryKind.EXPENSE).count() == 1
    other = make_case(CaseType.ENFORCEMENT, ministry, "creditor", lawyer)
    block = enforcement_block()
    block["reddiyatList"] = block["reddiyatList"][1:]
    record = make_record(other, "2026/2", block, lawyer)
    result = import_finance(record)
    assert result["yazilan"] == 1


@pytest.mark.django_db
def test_civil_advance_paid_by_lawyer_and_skipped_other_payer(lawyer):
    client = Client.objects.create(
        kind="person",
        first_name="Test",
        last_name="Müvekkil",
        responsible_lawyer=lawyer,
        responsible_intern=lawyer,
    )
    case = make_case(CaseType.CIVIL, client, "plaintiff", lawyer)
    block = {
        "tahsilatList": [
            {
                "kayitId": 5,
                "makbuzNo": "4366",
                "odeyenKisi": "Davacı TEST MÜVEKKİL 10000000146 Vekili TEST AVUKAT",
                "tahsilatTuru": "Gider Avansı",
                "tahsilatTarihi": "Jan 31, 2024 8:35:28 AM",
                "tahsilatTutari": 20,
            },
            {
                "kayitId": 6,
                "makbuzNo": "1654",
                "odeyenKisi": "TEST MÜVEKKİL",
                "tahsilatTuru": "Gider Avansı",
                "tahsilatTarihi": "Jan 12, 2024 9:47:26 AM",
                "tahsilatTutari": 1120,
            },
            {
                "kayitId": 7,
                "makbuzNo": "9",
                "odeyenKisi": "TEST ÖDEYEN",
                "tahsilatTuru": "Gider Avansı",
                "tahsilatTarihi": "Jan 12, 2024 9:47:26 AM",
                "tahsilatTutari": 50,
            },
        ],
        "reddiyatList": [],
        "harcList": [
            {"odeyenKisi": "TEST ÖDEYEN", "tahsilatTuru": "Vekalet Suret Harcı", "miktar": 60.8},
            {"odeyenKisi": "TEST MÜVEKKİL", "tahsilatTuru": "Başvurma Harcı", "miktar": 427.6},
            {"odeyenKisi": "TEST MÜVEKKİL", "tahsilatTuru": "Peşin Harç", "miktar": 427.6},
        ],
    }
    record = make_record(case, "2024/33", block, lawyer, category="Hukuk Dava Dosyası")
    result = import_finance(record)
    assert result["yazilan"] == 2
    assert sorted(LedgerEntry.objects.values_list("amount", flat=True)) == [20, 1120]
    assert any("TEST ÖDEYEN" in note for note in result["notlar"])
    assert not any("harc" in note.lower() for note in result["notlar"])


@pytest.mark.django_db
def test_civil_fee_beyond_advance_is_reported_not_written(lawyer, ministry):
    case = make_case(CaseType.CIVIL, ministry, "plaintiff", lawyer)
    block = {
        "tahsilatList": [],
        "reddiyatList": [],
        "harcList": [{"odeyenKisi": BAKANLIK, "tahsilatTuru": "Peşin Harç", "miktar": 100}],
    }
    record = make_record(case, "2025/1", block, lawyer, category="Hukuk Dava Dosyası")
    result = import_finance(record)
    assert result["yazilan"] == 0 and any("fark" in note for note in result["notlar"])


@pytest.mark.django_db
def test_case_without_client_does_not_crash_and_writes_nothing(lawyer):
    case = make_case(CaseType.ENFORCEMENT, None, "", lawyer)
    record = make_record(case, "2026/77", enforcement_block(), lawyer)
    result = import_finance(record)
    assert result["yazilan"] == 0
    assert not LedgerEntry.objects.filter(case=case).exists()
