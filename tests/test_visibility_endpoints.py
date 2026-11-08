"""Sorumlu bazlı (restricted) görünürlükte uç (URL) bazında yetki testleri.

`filter_visible_cases` fonksiyonu tests/test_accounts.py içinde sınanır; burada görünmeyen
dosya/görev/duruşma/belgenin HTTP uçlarından okunamadığı, değiştirilemediği ve raporlara
sızmadığı doğrulanır. Veriler sentetiktir.
"""

import datetime as dt

import pytest
from django.core.files.base import ContentFile
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.cases.models import CaseEvent, Document, Hearing, Seizure
from apps.core.text import tr_upper
from apps.office.models import OfficeSettings, TaskType
from apps.tasks.models import Task, TaskDocument
from tests.conftest import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def restricted():
    office = OfficeSettings.load()
    office.case_visibility_mode = OfficeSettings.CaseVisibilityMode.RESTRICTED
    office.save(update_fields=["case_visibility_mode"])


@pytest.fixture
def stranger(db):
    """Hiçbir kayıtta sorumlu/yardımcı/görevli olmayan avukat."""
    return make_user("yabanci", User.Role.LAWYER)


@pytest.fixture
def enforcement(case_factory):
    return case_factory(case_type="enforcement", subject="Gizli icra")


@pytest.fixture
def task(case_factory, lawyer, intern):
    case = case_factory(subject="Gizli dava")
    return Task.objects.create(
        task_type=TaskType.objects.get(name="Müvekkil Görüşmesi"),
        title="gizli görev",
        case=case,
        client=case.client,
        assignee=intern,
        reviewer=lawyer,
        due_date=timezone.localdate(),
        created_by=lawyer,
    )


@pytest.fixture
def hearing(task):
    return Hearing.objects.create(
        case=task.case, starts_at=timezone.now() + dt.timedelta(days=3), created_by=task.created_by
    )


def login(user):
    client = HttpClient()
    client.force_login(user)
    return client


def case_urls(case, hearing, event):
    return [
        ("post", reverse("cases:hearing_add", args=[case.pk])),
        ("post", reverse("cases:hearing_result", args=[case.pk, hearing.pk])),
        ("post", reverse("cases:event_add", args=[case.pk])),
        ("post", reverse("cases:event_delete", args=[case.pk, event.pk])),
    ]


def test_case_records_endpoints_hide_invisible_case(restricted, task, hearing, stranger, lawyer):
    case = task.case
    event = CaseEvent.objects.create(
        case=case, kind=CaseEvent.Kind.NOTE, title="not", date=timezone.localdate()
    )
    other = login(stranger)
    for method, url in case_urls(case, hearing, event):
        assert getattr(other, method)(url, {}).status_code == 404, url
    assert Hearing.objects.filter(case=case).count() == 1
    assert CaseEvent.objects.filter(case=case).count() == 1
    # Sorumlu avukat için aynı uçlar çalışır (yalnızca erişim; geçersiz veri 200 döner).
    owner = login(lawyer)
    for method, url in case_urls(case, hearing, event):
        assert getattr(owner, method)(url, {}).status_code == 200, url


def test_hearing_creation_is_blocked_for_invisible_case(restricted, task, stranger):
    response = login(stranger).post(
        reverse("cases:hearing_add", args=[task.case.pk]),
        {"kind": "hearing", "starts_at": "2030-01-01T10:00", "authority": "X"},
    )
    assert response.status_code == 404
    assert not Hearing.objects.filter(case=task.case).exists()


def test_seizure_endpoints_hide_invisible_case(restricted, enforcement, stranger, lawyer):
    item = Seizure.objects.create(
        case=enforcement, kind="bank", seized_on=dt.date(2026, 1, 1), created_by=lawyer
    )
    other = login(stranger)
    assert other.get(reverse("cases:seizure_add", args=[enforcement.pk])).status_code == 404
    assert (
        other.get(reverse("cases:seizure_edit", args=[enforcement.pk, item.pk])).status_code == 404
    )
    assert login(lawyer).get(reverse("cases:seizure_add", args=[enforcement.pk])).status_code == 200


def test_task_endpoints_hide_invisible_task(restricted, task, stranger, intern):
    other = login(stranger)
    for name in ("detail", "update"):
        assert other.get(reverse(f"tasks:{name}", args=[task.pk])).status_code == 404, name
    for name in ("action", "note", "comment", "delete", "doc_upload"):
        assert other.post(reverse(f"tasks:{name}", args=[task.pk]), {}).status_code == 404, name
    assert other.get(reverse("tasks:petition_template", args=[task.pk])).status_code == 404
    assert Task.objects.filter(pk=task.pk).exists()
    # Görevin sorumlusu ve dosyanın sorumlusu açabilir.
    assert login(intern).get(reverse("tasks:detail", args=[task.pk])).status_code == 200


def test_task_list_all_scope_does_not_leak(restricted, task, stranger, lawyer):
    url = reverse("tasks:list") + "?kapsam=tumu"
    assert tr_upper(task.title) not in tr_upper(login(stranger).get(url).content.decode())
    assert tr_upper(task.title) in tr_upper(login(lawyer).get(url).content.decode())


def test_task_form_offers_only_visible_cases(restricted, task, case_factory, stranger):
    response = login(stranger).get(reverse("tasks:create") + f"?dosya={task.case.pk}")
    assert response.status_code == 200
    queryset = response.context["form"].fields["case"].queryset
    assert not queryset.filter(pk=task.case.pk).exists()
    assert response.context["form"].initial.get("case") is None


def test_case_options_hides_invisible_case(restricted, task, stranger, lawyer):
    url = reverse("tasks:case_options") + f"?id={task.case.pk}&all=1"
    assert login(stranger).get(url).json()["cases"] == []
    assert len(login(lawyer).get(url).json()["cases"]) == 1


def test_hearing_list_endpoints_hide_invisible_hearing(restricted, hearing, stranger, lawyer):
    other = login(stranger)
    assert other.get(reverse("hearings:edit", args=[hearing.pk])).status_code == 404
    assert other.get(reverse("hearings:detail", args=[hearing.pk])).status_code == 404
    assert other.get(reverse("hearings:result", args=[hearing.pk])).status_code == 404
    assert other.get(reverse("hearings:task_create", args=[hearing.pk])).status_code == 404
    assert login(lawyer).get(reverse("hearings:detail", args=[hearing.pk])).status_code == 200
    # Oluşturan, yönetici veya kıdemli olmayan avukat görür ama düzenleyemez.
    hearing.created_by = None
    hearing.save()
    assert login(lawyer).get(reverse("hearings:edit", args=[hearing.pk])).status_code == 403


def test_standalone_hearing_form_ignores_invisible_case(restricted, task, stranger):
    response = login(stranger).get(reverse("hearings:create") + f"?dosya={task.case.pk}")
    assert response.status_code == 200
    assert response.context["form"].fields["case"].initial is None


def report_html(user, key, **params):
    response = login(user).get(reverse("reports:report", args=[key]), {"goster": "1", **params})
    assert response.status_code == 200
    return response.content.decode()


def test_reports_exclude_invisible_cases(restricted, task, enforcement, stranger, lawyer):
    for key in ("dosya-listesi", "dosya-son-durum"):
        assert task.case.subject.upper() not in report_html(stranger, key).upper(), key
    assert task.case.archive_reference in report_html(lawyer, "dosya-listesi")
    assert "gizli görev".upper() not in report_html(stranger, "gorevler").upper()
    assert "GİZLİ GÖREV" in report_html(lawyer, "gorevler").upper()


def test_media_checks_record_visibility(restricted, task, stranger, lawyer):
    case_doc = Document(case=task.case, title="d", original_name="d.pdf")
    case_doc.file.save("d.pdf", ContentFile(b"%PDF"), save=False)
    case_doc.save()
    task_doc = TaskDocument(task=task, original_name="g.pdf", uploaded_by=lawyer)
    task_doc.file.save("g.pdf", ContentFile(b"%PDF"), save=False)
    task_doc.save()
    for url in (case_doc.file.url, task_doc.file.url):
        assert login(stranger).get(url).status_code == 404, url
        assert login(lawyer).get(url).status_code == 200, url


def test_public_mode_keeps_everything_visible(task, stranger):
    assert login(stranger).get(reverse("tasks:detail", args=[task.pk])).status_code == 200
