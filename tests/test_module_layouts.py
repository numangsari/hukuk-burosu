import datetime as dt
import io
from html.parser import HTMLParser

import pytest
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounting.models import LedgerEntry
from apps.accounting.services import cancel_entry
from apps.cases.models import Seizure
from apps.office.models import TaskType
from apps.reports.definitions import build_cases, build_client_cases, build_seizures
from apps.tasks.models import Task, TaskEvent

pytestmark = pytest.mark.django_db


def make_task(case, **kwargs):
    data = dict(
        case=case,
        title="Örnek görev",
        task_type=TaskType.objects.first(),
        due_date=timezone.localdate(),
        assignee=case.responsible_intern,
        reviewer=case.responsible_lawyer,
    )
    data.update(kwargs)
    return Task.objects.create(**data)


def test_tasks_filters_scope_deadlines_search_and_sort(lawyer_client, case_factory):
    case = case_factory(authority="Örnek Mahkeme", official_no="2026/452")
    today = timezone.localdate()
    first = make_task(case, title="Birinci iş", due_date=today + dt.timedelta(days=2))
    second = make_task(
        case, title="İkinci iş", status="review", due_date=today + dt.timedelta(days=3)
    )
    make_task(case, status="done", due_date=today + dt.timedelta(days=2))
    make_task(case, due_date=today + dt.timedelta(days=4))
    url = reverse("tasks:list")
    params = {
        "kapsam": "tumu",
        "son_gun": "soon",
        "q": "2026/452",
        "sorumlu": case.responsible_intern_id,
        "kontrolcu": case.responsible_lawyer_id,
        "sort": "-due_date",
    }
    response = lawyer_client.get(url, params)
    assert [row.pk for row in response.context["tasks"]] == [first.pk]
    html = response.content.decode()
    assert 'name="sorumlu"' in html and 'name="kontrolcu"' in html
    assert "Kontrolde olanlar" in html and 'name="sort"' in html
    response = lawyer_client.get(url, {**params, "sekme": "kontrolde"}, HTTP_HX_REQUEST="true")
    assert [row.pk for row in response.context["tasks"]] == [second.pk]
    assert lawyer_client.get(url, {"kapsam": "bana"}).context["paginator"].count == 0
    response = lawyer_client.get(url, {"sekme": "bekleyen", "sort": "bad", "sorumlu": "bad"})
    assert response.status_code == 200 and response.context["paginator"].count == 1


def test_accounting_search_case_cancelled_sort_and_filtered_totals(
    admin_client_logged, case_factory
):
    case = case_factory()
    today = timezone.localdate()
    first = LedgerEntry.objects.create(
        client=case.client,
        case=case,
        kind="fee",
        amount="100",
        date=today,
        description="Örnek gider",
    )
    second = LedgerEntry.objects.create(
        client=case.client,
        case=case,
        kind="fee",
        amount="200",
        date=today,
        description="Örnek gider",
    )
    cancelled = LedgerEntry.objects.create(
        client=case.client,
        case=case,
        kind="fee",
        amount="9000",
        date=today,
        description="Örnek gider",
    )
    cancel_entry(cancelled, case.responsible_lawyer, "Örnek iptal nedeni")
    other = case_factory()
    LedgerEntry.objects.create(
        client=other.client, kind="fee", amount="500", date=today, description="Başka kayıt"
    )
    url = reverse("accounting:list")
    params = {"q": "gider", "dosya": case.pk, "musteri": case.client_id, "sort": "-amount"}
    response = admin_client_logged.get(url, params)
    assert [entry.pk for entry in response.context["entries"]] == [second.pk, first.pk]
    assert response.context["balances"]["debt"] == 300
    response = admin_client_logged.get(
        url, {**params, "durum": "cancelled"}, HTTP_HX_REQUEST="true"
    )
    assert [entry.pk for entry in response.context["entries"]] == [cancelled.pk]
    assert response.context["balances"]["debt"] == 0
    assert (
        "Örnek iptal nedeni" in response.content.decode()
        and 'hx-swap-oob="true"' in response.content.decode()
    )
    assert (
        admin_client_logged.get(url, {"iptal": "1", "dosya": case.pk}).context["paginator"].count
        == 3
    )


def test_accounting_filters_never_expose_balances_to_intern(client, intern):
    client.force_login(intern)
    html = client.get(
        reverse("accounting:list"), {"durum": "all"}, HTTP_HX_REQUEST="true"
    ).content.decode()
    assert "acc-summary" not in html and "Bakiye tutar" not in html


def test_reports_have_groups_and_consistent_seizure_data(admin_client_logged, case_factory, lawyer):
    case = case_factory(case_type="enforcement", stage="seizure")
    today = timezone.localdate()
    Seizure.objects.create(
        case=case,
        debtor="Örnek borçlu",
        asset="Örnek araç",
        seized_on=today,
        renewal_on=today + dt.timedelta(days=10),
        created_by=lawyer,
    )
    result = build_seizures({}, lawyer)
    assert len(result.rows) == 1 and result.rows[0][2:4] == ["Örnek borçlu", "Örnek araç"]
    for result in [build_cases({}, lawyer), build_client_cases({}, lawyer)]:
        row = dict(zip([column.label for column in result.columns], result.rows[0], strict=True))
        assert row["Aşama / Kapanma nedeni"] == "Haciz aşaması"
        assert row["Aktif haciz"] == 1 and row["Yenileme tarihi"] == today + dt.timedelta(days=10)
    html = admin_client_logged.get(reverse("reports:index")).content.decode()
    for label in [
        "Dosya raporları",
        "Görev raporları",
        "Mali raporlar",
        "Haciz ve yenileme takibi",
    ]:
        assert label in html
    url = reverse("reports:report", args=["haciz-takibi"])
    preview = admin_client_logged.get(url, {"goster": "1"})
    columns = [column.label for column in preview.context["result"].columns]
    exported = admin_client_logged.get(url, {"format": "xlsx"})
    sheet = load_workbook(io.BytesIO(exported.content)).active
    header = next(row for row in sheet.iter_rows(values_only=True) if row[0] == columns[0])
    assert list(header) == columns
    assert admin_client_logged.get(url, {"format": "pdf"}).content.startswith(b"%PDF")
    assert "Örnek araç" in preview.content.decode()
    invalid = admin_client_logged.get(
        url, {"goster": "1", "start": "2026-11-03", "end": "2026-11-01"}
    )
    assert "end" in invalid.context["form"].errors and invalid.context["result"] is None


class StructureParser(HTMLParser):
    checked = {"div", "form", "ul", "li", "table", "thead", "tbody", "tr", "td", "th", "section"}

    def __init__(self):
        super().__init__()
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag in self.checked:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.checked:
            assert self.stack and self.stack[-1] == tag, (tag, self.stack)
            self.stack.pop()


def test_forms_task_tabs_and_report_pages_have_balanced_layout(lawyer_client, case_factory):
    task = make_task(case_factory())
    TaskEvent.objects.create(task=task, kind="comment", comment="Örnek yorum", actor=task.reviewer)
    TaskEvent.objects.create(
        task=task, kind="updated", comment="Örnek düzenleme", actor=task.reviewer
    )
    urls = [
        reverse("tasks:create"),
        task.get_absolute_url(),
        reverse("tasks:list"),
        reverse("accounting:create"),
        reverse("accounting:list"),
        reverse("reports:index"),
        reverse("reports:report", args=["haciz-takibi"]) + "?goster=1",
    ]
    for url in urls:
        response = lawyer_client.get(url)
        assert response.status_code == 200
        parser = StructureParser()
        parser.feed(response.content.decode())
        assert not parser.stack, (url, parser.stack)
    response = lawyer_client.get(task.get_absolute_url())
    assert [event.comment for event in response.context["comments"]] == ["Örnek yorum"]
    assert [event.comment for event in response.context["events"]] == ["Örnek düzenleme"]
    assert 'id="task-docs"' in response.content.decode()
    assert 'id="task-history"' not in response.content.decode()


def test_new_forms_can_open_in_same_site_window(lawyer_client):
    for name in (
        "tasks:create",
        "accounting:create",
        "cases:create",
        "clients:create",
        "hearings:create",
        "archive:create",
    ):
        response = lawyer_client.get(reverse(name) + "?pencere=1")
        assert response.status_code == 200
        assert response["X-Frame-Options"] == "SAMEORIGIN"
        assert "<form" in response.content.decode()


@pytest.mark.parametrize("page", ["core:home", "cases:list", "clients:list", "tasks:list"])
def test_topbar_has_one_create_menu_on_every_page(lawyer_client, page):
    html = lawyer_client.get(reverse(page)).content.decode()
    assert html.count(">Yeni kayıt<") == 1
    for name in (
        "tasks:create",
        "cases:create",
        "clients:create",
        "hearings:create",
        "archive:create",
    ):
        assert reverse(name) in html


def test_create_menu_is_not_duplicated_on_home_page_header(lawyer_client):
    html = lawyer_client.get(reverse("core:home")).content.decode()
    assert "Yeni kayıt oluştur" not in html


def test_create_menu_hidden_inside_modal_frame(lawyer_client):
    html = lawyer_client.get(reverse("cases:list") + "?pencere=1").content.decode()
    assert ".topbar" in html and "display: none" in html  # üst çubuk pop-up içinde gizlenir
