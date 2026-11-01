import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounting.models import LedgerEntry
from apps.cases.models import Case
from apps.clients.models import Client
from apps.imports import services

from .conftest import VALID_TCKN

pytestmark = pytest.mark.django_db


def workbook(clients=(), cases=(), balances=()):
    """Şablondan başlayıp örnek satırları silerek verilen satırlarla doldurur."""
    wb = load_workbook(io.BytesIO(services.template_bytes()))
    for name, rows in (
        ("Müvekkiller", clients),
        ("Dosyalar", cases),
        ("Açılış bakiyeleri", balances),
    ):
        ws = wb[name]
        ws.delete_rows(2, ws.max_row)
        for r in rows:
            ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def client_row(kind="Gerçek", first="Ayşe", last="DENEME", tckn="", title="", **kw):
    row = [kind, first, last, tckn, title, kw.get("vkn", ""), "", kw.get("phone", ""), "", "", kw.get("iban", ""),
           kw.get("lawyer", ""), kw.get("intern", ""), ""]  # fmt: skip
    return row


def case_row(client="Ayşe DENEME", archive="2026/0900", subject="Alacak", **kw):
    return [client, kw.get("type", "Hukuk Davası"), archive, "", "", subject, kw.get("status", "Açık"),
            kw.get("stage", ""), kw.get("value", ""), kw.get("opened", "15.01.2026"), "", "", ""]  # fmt: skip


def test_template_has_sheets_and_headers():
    wb = load_workbook(io.BytesIO(services.template_bytes()))
    assert wb.sheetnames == ["Açıklamalar", "Müvekkiller", "Dosyalar", "Açılış bakiyeleri"]
    assert [c.value for c in wb["Dosyalar"][1]] == services.CASE_COLS


def test_plan_and_execute(lawyer, intern, admin_user):
    f = workbook(
        clients=[client_row(tckn=VALID_TCKN, phone="0555 000 00 00", iban="TR33 0006 1005 1978 6457 8413 26"),
                 client_row(kind="Tüzel", first="", last="", title="Deneme Ticaret A.Ş.")],
        cases=[case_row(value="150.000,50", stage="İstinaf incelemesi"), case_row(client="Deneme Ticaret A.Ş.", archive="2026/0901", type="İcra Takibi")],
        balances=[["Ayşe DENEME", "31.12.2025", "25000", "1000", ""]],
    )  # fmt: skip
    plan = services.build_plan(f, lawyer, intern)
    assert not plan.errors, [r.messages for r in plan.errors]
    counts = services.execute(plan, admin_user)
    assert counts == {"clients": 2, "cases": 2, "balances": 1}
    ayse = Client.objects.get(tckn=VALID_TCKN)
    assert ayse.responsible_lawyer == lawyer and ayse.contacts.get().value == "0555 000 00 00"
    assert ayse.ibans.get().iban == "TR330006100519786457841326"
    case = Case.objects.get(archive_no="2026/0900")
    assert case.value == Decimal("150000.50") and case.stage == "appeal" and case.client == ayse
    assert Case.objects.get(archive_no="2026/0901").case_type == "enforcement"
    b = LedgerEntry.objects.filter(client=ayse).balances()
    assert (b["debt"], b["credit"], b["balance"]) == (
        Decimal("25000"),
        Decimal("1000"),
        Decimal("24000"),
    )


def test_duplicates_and_errors_reported(lawyer, intern, client_factory, case_factory):
    existing = client_factory(first_name="Mevcut", last_name="KİŞİ", tckn=VALID_TCKN)
    case_factory(client=existing, archive_no="2026/0001")
    f = workbook(
        clients=[
            client_row(first="mevcut", last="kişi"),  # kimliksiz aynı ad: karar kullanıcıya bırakılır
            client_row(first="Başka", last="BİRİ", tckn=VALID_TCKN),  # aynı TCKN: atlanır
            client_row(tckn="12345678901"),  # geçersiz TCKN
            client_row(first="", last=""),
        ],
        cases=[case_row(client="Mevcut KİŞİ", archive="2026/0001"), case_row(client="Olmayan Kişi", archive="X1"),
               case_row(client=VALID_TCKN, archive="X2", type="Uzay Davası")],
    )  # fmt: skip
    plan = services.build_plan(f, lawyer, intern)
    statuses = [(r.sheet, r.status) for r in plan.rows]
    assert statuses == [
        ("Müvekkiller", "error"), ("Müvekkiller", "skip"), ("Müvekkiller", "error"), ("Müvekkiller", "error"),
        ("Dosyalar", "skip"), ("Dosyalar", "error"), ("Dosyalar", "error"),
    ]  # fmt: skip
    assert "TCKN/VKN yazın" in plan.rows[0].messages[0]
    with pytest.raises(ValueError):
        services.execute(plan, lawyer)
    assert Client.objects.count() == 1  # hiçbir şey yazılmadı


def test_same_name_different_identity_is_created(lawyer, intern, client_factory):
    from .conftest import VALID_TCKN as T1

    client_factory(first_name="Ali", last_name="VELİ")  # kimliksiz mevcut kayıt
    plan = services.build_plan(
        workbook(clients=[client_row(first="Ali", last="VELİ", tckn=T1)]), lawyer, intern
    )
    assert plan.rows[0].status == "create" and "aynı adlı" in plan.rows[0].messages[0]


def test_ambiguous_client_name_in_cases(lawyer, intern, client_factory):
    client_factory(first_name="Ali", last_name="VELİ")
    client_factory(first_name="Ali", last_name="VELİ", tckn=VALID_TCKN)
    plan = services.build_plan(workbook(cases=[case_row(client="Ali VELİ")]), lawyer, intern)
    assert plan.rows[0].status == "error" and "birden fazla" in plan.rows[0].messages[0]
    plan = services.build_plan(workbook(cases=[case_row(client=VALID_TCKN)]), lawyer, intern)
    assert plan.rows[0].status == "create"  # TCKN ile kesin eşleşir


def test_same_file_and_same_balance_not_imported_twice(admin_user, lawyer, intern, client_factory):
    import hashlib

    c = client_factory(first_name="Ayşe", last_name="DENEME")
    data = workbook(balances=[["Ayşe DENEME", "31.12.2025", "1000", "0", ""]]).read()
    digest = hashlib.sha256(data).hexdigest()
    plan = services.build_plan(io.BytesIO(data), lawyer, intern, file_hash=digest)
    services.execute(plan, admin_user, file_hash=digest, file_name="veri.xlsx")
    again = services.build_plan(io.BytesIO(data), lawyer, intern, file_hash=digest)
    assert again.errors and "zaten aktarıldı" in again.errors[0].messages[0]
    # Farklı dosyada aynı devir satırı: atlanır
    other = services.build_plan(
        workbook(balances=[["Ayşe DENEME", "31.12.2025", "1000", "0", ""]]), lawyer, intern
    )
    assert other.rows[0].status == "skip" and LedgerEntry.objects.filter(client=c).count() == 1


def test_client_matching_party_imports_without_confirmation(admin_user, lawyer, intern):
    from apps.clients.models import Party

    Party.objects.create(kind="person", name="Ayşe DENEME")
    c = HttpClient()
    c.force_login(admin_user)
    upload = SimpleUploadedFile("veri.xlsx", workbook(clients=[client_row()]).read())
    r = c.post(
        reverse("imports:import"),
        {"file": upload, "default_lawyer": lawyer.pk, "default_intern": intern.pk},
    )
    data = {"token": r.context["token"], "default_lawyer": lawyer.pk, "default_intern": intern.pk}
    c.post(reverse("imports:import"), data)
    assert Client.objects.count() == 1  # çıkar çatışması onayı istenmez


def test_unknown_responsible_user_is_error(lawyer, intern):
    plan = services.build_plan(
        workbook(clients=[client_row(lawyer="Olmayan Avukat")]), lawyer, intern
    )
    assert plan.errors and "bulunamadı" in plan.errors[0].messages[0]


def test_import_views_admin_only_and_two_step(admin_user, lawyer, intern):
    c = HttpClient()
    c.force_login(lawyer)
    assert c.get(reverse("imports:import")).status_code == 403
    c.force_login(admin_user)
    assert c.get(reverse("imports:template"))["Content-Type"].startswith("application/vnd.openxml")
    upload = SimpleUploadedFile("veri.xlsx", workbook(clients=[client_row()]).read())
    r = c.post(
        reverse("imports:import"),
        {"file": upload, "default_lawyer": lawyer.pk, "default_intern": intern.pk},
    )
    assert r.status_code == 200 and not Client.objects.exists()  # yalnızca önizleme
    token = r.context["token"]
    r = c.post(
        reverse("imports:import"),
        {"token": token, "default_lawyer": lawyer.pk, "default_intern": intern.pk},
    )
    assert r.status_code == 302 and Client.objects.count() == 1
    r = c.post(
        reverse("imports:import"),
        {"token": "../../etc", "default_lawyer": lawyer.pk, "default_intern": intern.pk},
    )
    assert Client.objects.count() == 1  # geçersiz token reddedilir


def test_bad_file_rejected(admin_user, lawyer, intern):
    c = HttpClient()
    c.force_login(admin_user)
    r = c.post(reverse("imports:import"), {"file": SimpleUploadedFile("x.xlsx", b"bozuk"), "default_lawyer": lawyer.pk,
                                           "default_intern": intern.pk})  # fmt: skip
    assert "file" in r.context["form"].errors


def test_closed_case_import_needs_closing_reason(lawyer, intern):
    clients = [client_row()]
    plan = services.build_plan(
        workbook(clients=clients, cases=[case_row(status="Kapalı")]), lawyer, intern
    )
    case_result = [r for r in plan.rows if r.sheet == "Dosyalar"][0]
    assert case_result.status == "error" and "kapanma nedeni" in case_result.messages[0].lower()
    plan = services.build_plan(
        workbook(
            clients=clients,
            cases=[case_row(status="Kapalı", stage="Feragat nedeniyle sonuçlandı")],
        ),
        lawyer,
        intern,
    )
    case_result = [r for r in plan.rows if r.sheet == "Dosyalar"][0]
    assert case_result.status == "create", case_result.messages
