import io
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounting.models import EntryKind, LedgerEntry
from apps.cases.models import CaseParty
from apps.clients.models import Party
from apps.office.models import TaskType
from apps.reports.base import Column, ReportResult
from apps.reports.renderers import to_xlsx
from apps.tasks import services
from apps.tasks.models import Task, TaskDocument

pytestmark = pytest.mark.django_db


def login(user):
    client = HttpClient()
    client.force_login(user)
    return client


@pytest.fixture
def task(case_factory, intern, lawyer):
    return Task.objects.create(
        task_type=TaskType.objects.get(name="Dilekçe"),
        title="Örnek dilekçe",
        case=case_factory(),
        assignee=intern,
        reviewer=lawyer,
        created_by=lawyer,
        due_date=timezone.localdate(),
    )


@pytest.mark.parametrize("role", ["intern", "lawyer", "admin_user"])
def test_case_record_delete_requires_admin(request, role, case_factory):
    case = case_factory()
    party = Party.objects.create(kind="person", name="Örnek Karşı Taraf")
    item = CaseParty.objects.create(case=case, party=party, role="defendant")
    route = "cases:party_remove"
    client = login(request.getfixturevalue(role))
    url = reverse(route, args=[case.pk, item.pk])
    assert (url in client.get(case.get_absolute_url()).content.decode()) == (role == "admin_user")
    response = client.post(url)
    assert response.status_code == (200 if role == "admin_user" else 403)
    assert type(item).objects.filter(pk=item.pk).exists() == (role != "admin_user")


@pytest.mark.parametrize("role", ["intern", "lawyer", "admin_user"])
@pytest.mark.parametrize("kind", ["iletisim", "iban", "yetkili", "vekalet"])
def test_client_subrecord_delete_requires_admin(request, role, kind, client_factory):
    from tests.conftest import client_form_data

    owner = (
        client_factory(kind="company", title="Örnek Şirket")
        if kind == "yetkili"
        else client_factory()
    )
    if kind == "iletisim":
        item = owner.contacts.create(kind="phone", value="0000000000")
    elif kind == "iban":
        item = owner.ibans.create(iban="TR330006100519786457841326")
    elif kind == "yetkili":
        item = owner.representatives.create(name="Örnek Yetkili")
    else:
        item = owner.powers_of_attorney.create(
            notary="Örnek Noter", date=timezone.localdate(), journal_no="1"
        )
    client = login(request.getfixturevalue(role))
    url = reverse("clients:update", args=[owner.pk])
    page = client.get(url).content.decode()
    # Silme kutusu yalnızca yöneticinin formunda çıkar; diğerlerinde silme yok sayılır.
    assert (f'name="{kind}-0-DELETE"' in page) == (role == "admin_user")
    client.post(url, client_form_data(owner, delete={(kind, item.pk)}))
    assert type(item).objects.filter(pk=item.pk).exists() == (role != "admin_user")


def add_entry(owner, kind, amount):
    return LedgerEntry.objects.create(
        client=owner, kind=kind, amount=Decimal(amount), date=timezone.localdate()
    )


def test_trust_income_can_be_cancelled_after_payment(admin_user, client_factory):
    # Karşı taraftan tahsilat, ödeme yapılmış olsa da iptal edilebilir.
    owner = client_factory()
    income = add_entry(owner, EntryKind.TRUST_IN, "10000")
    add_entry(owner, EntryKind.TRUST_OUT, "7000")
    client = login(admin_user)
    client.post(reverse("accounting:cancel", args=[income.pk]), {"reason": "Yanlış kayıt"})
    income.refresh_from_db()
    assert income.is_cancelled
    assert owner.ledger_entries.balances()["balance"] == Decimal("7000")


def test_approve_rechecks_required_document(task, lawyer):
    Task.objects.filter(pk=task.pk).update(status="review")
    task.refresh_from_db()
    with pytest.raises(ValidationError):
        services.perform(task, "approve", lawyer)
    task.refresh_from_db()
    assert task.status == "review"
    assert not task.events.exists()
    assert not task.case.events.exists()


def test_stale_approval_does_not_publish_twice(task, intern, lawyer, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    TaskDocument.objects.create(
        task=task,
        file=SimpleUploadedFile("ornek.pdf", b"%PDF"),
        original_name="ornek.pdf",
        kind=TaskDocument.Kind.PETITION,
        uploaded_by=intern,
    )
    services.perform(task, "submit", intern)
    stale_task = Task.objects.get(pk=task.pk)
    services.perform(task, "approve", lawyer)
    with pytest.raises(ValidationError):
        services.perform(stale_task, "approve", lawyer)
    assert task.events.filter(kind="approved").count() == 1
    assert task.case.documents.count() == 1
    assert task.case.events.filter(kind="task").count() == 1


def test_excel_preserves_formula_like_text():
    text = '=HYPERLINK("https://example.invalid", "Örnek")'
    result = ReportResult(
        title=text,
        subtitle=text,
        columns=[Column(text), Column("Tutar", "money")],
        rows=[[text, Decimal("123.45")]],
        totals=[text, Decimal("123.45")],
        summary=[(text, text)],
    )
    workbook = load_workbook(io.BytesIO(to_xlsx(result, text)))
    cells = [cell for row in workbook.active for cell in row if cell.value == text]
    assert len(cells) == 8
    assert all(cell.data_type == "s" for cell in cells)
    assert workbook.active.cell(9, 2).value == 123.45


def test_client_title_contains_only_text(lawyer_client, client_factory):
    response = lawyer_client.get(client_factory().get_absolute_url())
    title = response.content.decode().split("<title>", 1)[1].split("</title>", 1)[0]
    assert "<script>" not in title
    assert "DOMContentLoaded" not in title


@pytest.mark.parametrize("reason", ["", "Örnek düzeltme"])
def test_messages_close_after_ten_seconds_or_on_request(reason, admin_user, client_factory):
    entry = add_entry(client_factory(), EntryKind.FEE, "10")
    response = login(admin_user).post(
        reverse("accounting:cancel", args=[entry.pk]), {"reason": reason}, follow=True
    )
    notices = response.content.decode().split('class="toast-stack"', 1)[1]
    assert 'x-init="setTimeout(() => show = false, 10000)"' in notices
    assert 'x-show.important="show"' in notices
    assert 'aria-label="Bildirimi kapat"' in notices
