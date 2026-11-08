import pytest
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import EntryKind, LedgerEntry
from apps.imports.models import PortalNotice

pytestmark = pytest.mark.django_db


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def lists(case):
    return {
        "cases": reverse("cases:list"),
        "clients": reverse("clients:list"),
        "tasks": reverse("tasks:list"),
        "accounting": reverse("accounting:list"),
        "notices": reverse("notice_list"),
        "hearings": reverse("hearings:export"),
    }


@pytest.mark.parametrize("kind", ["xlsx", "pdf"])
def test_every_list_exports_excel_and_pdf(admin_user, case_factory, kind):
    case = case_factory()
    LedgerEntry.objects.create(
        client=case.client, case=case, kind=EntryKind.FEE, amount=100, date=timezone.localdate()
    )
    PortalNotice.objects.create(
        fingerprint="n1", subject="Örnek tebligat", delivered_at=timezone.now()
    )
    c = login(admin_user)
    for name, url in lists(case).items():
        response = c.get(url, {"export": kind})
        assert response.status_code == 200, name
        expected = "application/pdf" if kind == "pdf" else "spreadsheetml"
        assert expected in response["Content-Type"], name
        assert f".{kind}" in response["Content-Disposition"], name
        assert len(response.content) > 500, name


def test_export_ignores_pagination_and_applies_filters(admin_user, case_factory, client_factory):
    from io import BytesIO

    from openpyxl import load_workbook

    for _ in range(3):
        case_factory()
    target = case_factory()
    c = login(admin_user)

    def rows(**params):
        r = c.get(reverse("cases:list"), {"export": "xlsx", **params})
        sheet = load_workbook(BytesIO(r.content)).active
        return [row for row in sheet.iter_rows(min_row=1, values_only=True) if row[0]]

    all_rows = rows(page=2)  # sayfa numarası yok sayılır
    assert len(all_rows) >= 4
    filtered = rows(q=target.archive_no)
    assert any(target.archive_no in str(cell) for row in filtered for cell in row if cell)
    assert len(filtered) < len(all_rows)


def test_export_requires_login_and_respects_visibility(case_factory, intern, client_factory):
    # Girişsiz kullanıcı yönlendirilir; görünürlük dışındaki dosya çıktıda yer almaz.
    anon = HttpClient()
    assert anon.get(reverse("accounting:list"), {"export": "pdf"}).status_code in (302, 403)
    from apps.accounts.models import User

    stranger = User.objects.create_user(username="baska-avukat", role=User.Role.LAWYER)
    foreign = case_factory(
        client=client_factory(responsible_lawyer=stranger, responsible_intern=None)
    )
    from apps.office.models import OfficeSettings

    OfficeSettings.load().set_role_permission("cases.view_all", [])
    response = login(intern).get(reverse("cases:list"), {"export": "xlsx"})
    assert response.status_code == 200
    from io import BytesIO

    from openpyxl import load_workbook

    text = " ".join(
        str(cell)
        for row in load_workbook(BytesIO(response.content)).active.iter_rows(values_only=True)
        for cell in row
        if cell
    )
    assert foreign.archive_no not in text


def test_export_buttons_render_without_template_comment_text(admin_user, case_factory):
    case_factory()
    c = login(admin_user)
    for url in (reverse("notice_list"), reverse("cases:list"), reverse("clients:list")):
        html = c.get(url).content.decode()
        assert 'data-export-link="xlsx"' in html and 'data-export-link="pdf"' in html
        assert "{#" not in html and "#}" not in html
