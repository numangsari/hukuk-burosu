import datetime as dt

import pytest
from django.utils import timezone

from apps.accounting.models import EntryKind, LedgerEntry
from apps.cases.models import CaseStatus, Hearing, HearingKind
from apps.imports.models import PortalNotice
from apps.reports import definitions as d

pytestmark = pytest.mark.django_db


def test_case_report_filters_by_client_status_and_team(admin_user, case_factory, client_factory):
    mine = case_factory()
    other = case_factory(client=client_factory(first_name="Başka"))
    closed = case_factory(client=mine.client, status=CaseStatus.CLOSED)
    all_rows = d.build_cases({"status": "all"}, admin_user).rows
    assert len(all_rows) == 3
    by_client = d.build_cases({"client": mine.client, "status": "all"}, admin_user)
    assert {r[0] for r in by_client.rows} == {mine.archive_reference, closed.archive_reference}
    open_only = d.build_cases({"client": mine.client}, admin_user)
    assert [r[0] for r in open_only.rows] == [mine.archive_reference]
    by_lawyer = d.build_cases({"lawyer": other.responsible_lawyer, "status": "all"}, admin_user)
    assert len(by_lawyer.rows) == 3  # fabrika aynı avukatı atar
    by_intern = d.build_cases({"intern": mine.responsible_intern, "status": "all"}, admin_user)
    assert len(by_intern.rows) == 3
    labels = [c.label for c in all_rows and by_client.columns]
    assert "Yardımcı sorumlu" in labels


def test_client_reports(admin_user, case_factory, client_factory, lawyer):
    case = case_factory()
    case_factory(client=case.client)
    other = case_factory(client=client_factory(first_name="Diğer"))
    listing = d.build_clients({}, admin_user)
    assert len(listing.rows) == 2 and "Bakiye" in [c.label for c in listing.columns]
    assert [r[0] for r in d.build_clients({"lawyer": lawyer}, admin_user).rows]
    result = d.build_client_cases({"client": case.client, "status": "all"}, admin_user)
    assert result.title == "Dosya Durum Raporu" and len(result.rows) == 2
    tasks = d.build_client_tasks({"client": other.client}, admin_user)
    assert tasks.title.startswith("Müvekkil Görev Raporu") and tasks.rows == []


def test_ledger_report_filters_state_source_and_kind(admin_user, case_factory):
    case = case_factory()
    today = timezone.localdate()

    def add(**kw):
        kw.setdefault("kind", EntryKind.FEE)
        return LedgerEntry.objects.create(
            client=case.client, case=case, amount=100, date=today, **kw
        )

    add()
    add(is_cancelled=True, cancelled_at=timezone.now())
    add(portal_ref="u1", excluded_from_balance=True)
    add(portal_ref="u2", kind=EntryKind.EXPENSE)
    assert len(d.build_ledger({}, admin_user).rows) == 2  # varsayılan: geçerli kayıtlar
    assert len(d.build_ledger({"state": "all"}, admin_user).rows) == 4
    assert len(d.build_ledger({"state": "cancelled"}, admin_user).rows) == 1
    assert len(d.build_ledger({"state": "excluded"}, admin_user).rows) == 1
    uyap = d.build_ledger({"state": "all", "source": "uyap"}, admin_user)
    assert {r[-1] for r in uyap.rows} == {"UYAP"} and len(uyap.rows) == 2
    assert len(d.build_ledger({"kind": EntryKind.EXPENSE}, admin_user).rows) == 1


def test_hearing_report_filters(admin_user, case_factory, lawyer):
    case = case_factory()

    def make(days, **kw):
        return Hearing.objects.create(
            case=case,
            kind=HearingKind.HEARING,
            starts_at=timezone.now() + dt.timedelta(days=days),
            assigned_to=kw.pop("assigned_to", lawyer),
            **kw,
        )

    make(3)
    make(5, excuse_submitted=True)
    make(7, assigned_to=None)
    Hearing.objects.create(
        case=case, kind=HearingKind.OFFICE_MEETING, starts_at=timezone.now(), title="Toplantı"
    )  # listede yok
    assert len(d.build_hearings({}, admin_user).rows) == 3
    assert len(d.build_hearings({"attendance": "excuse"}, admin_user).rows) == 1
    assert len(d.build_hearings({"lawyer": lawyer}, admin_user).rows) == 2
    missing = d.build_hearings({"missing": True}, admin_user)
    assert len(missing.rows) == 1 and missing.rows[0][6] == "Seçilmedi"
    end = (timezone.localdate() + dt.timedelta(days=4)).isoformat()
    ranged = d.build_hearings({"end": dt.date.fromisoformat(end)}, admin_user)
    assert len(ranged.rows) == 1


def test_notice_report_filters_by_state(admin_user):
    now = timezone.now()
    PortalNotice.objects.create(fingerprint="a", subject="Bekleyen", delivered_at=now)
    PortalNotice.objects.create(
        fingerprint="b", subject="Görev yok", delivered_at=now, resolved_at=now
    )
    assert len(d.build_notices({}, admin_user).rows) == 2
    assert len(d.build_notices({"state": "pending"}, admin_user).rows) == 1
    assert len(d.build_notices({"state": "no_task"}, admin_user).rows) == 1
    assert len(d.build_notices({"state": "task"}, admin_user).rows) == 0


INTERNAL_LABELS = {"Sorumlu avukat", "Yardımcı sorumlu", "Arşiv yeri", "Açık görev", "Kontrolcü"}


def test_client_facing_reports_hide_office_internal_information(
    admin_user, case_factory, client_factory
):
    from apps.cases.models import CaseCoClient, CaseEvent

    case = case_factory()
    co = client_factory(first_name="Ortak", last_name="Müvekkil")
    CaseCoClient.objects.create(case=case, client=co, role="")
    CaseEvent.objects.create(
        case=case,
        date=timezone.localdate(),
        kind=CaseEvent.Kind.NOTE,
        title="İç not: avukat görüşü",
        created_by=admin_user,
    )
    CaseEvent.objects.create(
        case=case,
        date=timezone.localdate(),
        kind=CaseEvent.Kind.STATUS,
        title="Dosya incelemeye alındı",
        created_by=admin_user,
    )
    Hearing.objects.create(
        case=case,
        kind=HearingKind.HEARING,
        starts_at=timezone.now() + dt.timedelta(days=4),
        assigned_to=admin_user,
        excuse_submitted=True,
        result="İç sonuç notu",
        client_note="Müvekkile iletilecek açıklama",
    )
    cases = d.build_client_cases({"client": case.client, "status": "all"}, admin_user)
    assert not INTERNAL_LABELS & {c.label for c in cases.columns}
    text = " ".join(str(v) for row in cases.rows for v in row)
    assert "Dosya incelemeye alındı" in text and "İç not" not in text
    assert str(case.responsible_lawyer) not in text and str(admin_user) not in text
    hearings = d.build_client_hearings({"client": case.client}, admin_user)
    labels = {c.label for c in hearings.columns}
    assert not (INTERNAL_LABELS | {"Katılma", "Sonuç", "Müvekkil bilgilendirme"}) & labels
    row_text = " ".join(str(v) for row in hearings.rows for v in row)
    assert "Müvekkile iletilecek açıklama" in row_text
    assert "İç sonuç notu" not in row_text and "Mazeret" not in row_text
    assert co.name not in text  # ortak dosyada diğer müvekkilin adı yazılmaz
    shared = d.build_client_cases({"client": co, "status": "all"}, admin_user)
    assert case.client.name not in " ".join(str(v) for row in shared.rows for v in row)


def test_client_statement_excludes_cancelled_and_excluded_entries(admin_user, case_factory):
    case = case_factory()
    today = timezone.localdate()
    for kwargs in (
        {},
        {"is_cancelled": True, "cancelled_at": timezone.now()},
        {"portal_ref": "x", "excluded_from_balance": True},
    ):
        LedgerEntry.objects.create(
            client=case.client, case=case, kind=EntryKind.FEE, amount=100, date=today, **kwargs
        )
    result = d.build_statement({"client": case.client}, admin_user)
    assert len(result.rows) == 1
    assert "Arşiv" not in " ".join(c.label for c in result.columns)


def test_reports_index_balances_both_sides_into_four_or_five_categories(admin_client_logged):
    from django.urls import reverse

    page = admin_client_logged.get(reverse("reports:index"))
    client_groups = [g for g in page.context["client_groups"] if g["reports"]]
    office_groups = [g for g in page.context["office_groups"] if g["reports"]]
    assert 4 <= len(client_groups) <= 5 and 4 <= len(office_groups) <= 5
    client_keys = {k for g in client_groups for k in g["reports"]}
    assert client_keys == {
        "muvekkil-dosya-durumu",
        "muvekkil-durusmalari",
        "cari-ekstre",
        "muvekkil-masraf-ozeti",
        "muvekkil-tebligatlari",
    }
    office_keys = {k for g in office_groups for k in g["reports"]}
    assert "muvekkil-gorevleri" in office_keys and not office_keys & client_keys
    assert "reports-col-client" in page.content.decode()


def test_client_summary_groups_valid_entries_by_case(admin_user, case_factory):
    case = case_factory()
    today = timezone.localdate()
    for kind, amount, extra in (
        (EntryKind.FEE, 1000, {}),
        (EntryKind.COLLECTION, 400, {}),
        (EntryKind.EXPENSE, 50, {"is_cancelled": True, "cancelled_at": timezone.now()}),
        (EntryKind.EXPENSE, 70, {"portal_ref": "z", "excluded_from_balance": True}),
    ):
        LedgerEntry.objects.create(
            client=case.client, case=case, kind=kind, amount=amount, date=today, **extra
        )
    result = d.build_client_summary({"client": case.client}, admin_user)
    assert len(result.rows) == 1
    labels = [c.label for c in result.columns]
    row = dict(zip(labels, result.rows[0], strict=True))
    assert row[dict(EntryKind.choices)[EntryKind.FEE]] == 1000
    assert row[dict(EntryKind.choices)[EntryKind.EXPENSE]] == 0  # iptal/hesap dışı yok sayılır
    assert row["Bakiye"] == 600
    assert not INTERNAL_LABELS & set(labels)


def test_client_notice_report_lists_only_that_clients_notices(
    admin_user, case_factory, client_factory
):
    mine = case_factory()
    other = client_factory(first_name="Başka")
    now = timezone.now()
    PortalNotice.objects.create(
        fingerprint="m1",
        subject="Benim tebligat",
        delivered_at=now,
        resolution_client=mine.client,
        resolution_case=mine,
        resolved_at=now,
        no_task_reason="iç not",
    )
    PortalNotice.objects.create(
        fingerprint="o1", subject="Başkasının", delivered_at=now, resolution_client=other
    )
    result = d.build_client_notices({"client": mine.client}, admin_user)
    assert [r[2] for r in result.rows] == ["Benim tebligat"]
    assert "iç not" not in " ".join(str(v) for r in result.rows for v in r)
