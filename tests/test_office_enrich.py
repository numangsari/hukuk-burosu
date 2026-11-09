import pytest

from apps.cases.models import Case
from apps.imports.models import OfficeSourceRecord
from apps.imports.office_enrich import enrich, split_names

pytestmark = pytest.mark.django_db


def make_record(case, row, values, sheet="TEST"):
    return OfficeSourceRecord.objects.create(
        source_sha256="x",
        source_name="t.xlsx",
        sheet=sheet,
        row_number=row,
        values=values,
        case=case,
    )


def test_split_names_handles_multiple_debtors():
    assert split_names("A LTD ŞTİ , B ANONİM ŞİRKETİ") == ["A LTD ŞTİ", "B ANONİM ŞİRKETİ"]
    assert split_names("-") == []


def test_enforcement_row_fills_parties_stage_seizure_notes(
    admin_user, client_factory, case_factory
):
    owner = client_factory(first_name="Alacak", last_name="Sahibi")
    case = case_factory(client=owner, case_type="enforcement", client_role="creditor")
    Case.objects.filter(pk=case.pk).update(stage="")  # eski aktarım aşamasız bırakır
    make_record(
        case,
        2,
        {
            "ALACAKLI": owner.name,
            "BORÇLU": "BİRİNCİ BORÇLU",
            "KESİNLEŞME": "KESİN",
            "MAAŞ": "True",
            "BANKA": "False",
            "HACİZ NOTLARI": "Maaşa haciz konuldu",
        },
    )
    counts = enrich(apply=True)
    case = Case.objects.get(pk=case.pk)
    assert [(link.party.name, link.role) for link in case.party_links.all()] == [
        ("BİRİNCİ BORÇLU", "debtor")
    ]
    assert case.stage == "finalized"
    assert list(case.seizures.values_list("kind", "state")) == [("salary", "salary_applied")]
    assert "Eski liste · HACİZ NOTLARI: Maaşa haciz konuldu" in case.notes
    assert counts["parties"] == 1 and counts["seizures"] == 1
    # tekrar çalıştırma mükerrer kayıt üretmez
    again = enrich(apply=True)
    assert not any(again[k] for k in ("parties", "seizures", "stages", "notes"))


def test_dry_run_changes_nothing(admin_user, client_factory, case_factory):
    owner = client_factory(first_name="Alacak", last_name="Sahibi")
    case = case_factory(client=owner, case_type="enforcement", client_role="creditor")
    Case.objects.filter(pk=case.pk).update(stage="")  # eski aktarım aşamasız bırakır
    make_record(case, 2, {"ALACAKLI": owner.name, "BORÇLU": "X BORÇLU", "KESİNLEŞME": "KESİN"})
    assert enrich(apply=False)["parties"] == 1
    case.refresh_from_db()
    assert case.party_links.count() == 0 and case.stage == ""


def test_archive_row_adds_other_side_and_notes(admin_user, client_factory, case_factory):
    owner = client_factory(first_name="Davacı", last_name="Müvekkil")
    case = case_factory(client=owner, case_type="civil", client_role="plaintiff")
    make_record(
        case, 3, {"Davacı": owner.name, "Davalı": "KARŞI ŞİRKET LİMİTED ŞİRKETİ", "Not": "dikkat"}
    )
    enrich(apply=True)
    link = case.party_links.get()
    assert (link.party.name, link.role, link.party.kind) == (
        "KARŞI ŞİRKET LİMİTED ŞİRKETİ",
        "defendant",
        "company",
    )
    case.refresh_from_db()
    assert case.notes == "Eski liste · Not: dikkat"


def test_ambiguous_side_is_skipped(admin_user, client_factory, case_factory):
    owner = client_factory(first_name="Başka", last_name="Kişi")
    case = case_factory(client=owner, case_type="civil", client_role="plaintiff")
    make_record(case, 4, {"Davacı": "BİRİSİ", "Davalı": "BAŞKASI"})
    assert enrich(apply=True)["parties"] == 0
