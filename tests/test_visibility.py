"""Sorumlu bazlı görünürlükte uç (URL) düzeyi yetki testleri.

Kısıtlı modda dosyanın sorumlusu/yardımcısı olmayan bir avukat, dosya, görev, duruşma ve
belgelere hiçbir uçtan erişememeli; sorumlu avukat ve yönetici erişebilmelidir.
"""

import datetime as dt

import pytest
from django.core.files.base import ContentFile
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.cases.models import Case, CaseType, Document, Hearing, Seizure
from apps.office.models import OfficeSettings, TaskType
from apps.tasks.models import Task, TaskEvent

from .conftest import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def restricted_office(db):
    office = OfficeSettings.load()
    office.case_visibility_mode = OfficeSettings.CaseVisibilityMode.RESTRICTED
    office.save(update_fields=["case_visibility_mode"])
    return office


@pytest.fixture
def outsider(db):
    """Dosyanın sorumlusu olmayan avukat."""
    return make_user("disaridaki", User.Role.LAWYER)


@pytest.fixture
def owned(restricted_office, client_factory, case_factory, lawyer, intern):
    """Sorumlu avukatın dosyası, göreviyle, duruşmasıyla ve belgesiyle."""
    case = case_factory(client=client_factory())
    task = Task.objects.create(
        task_type=TaskType.objects.get(name="Müvekkil Görüşmesi"),
        title="Gizli görev",
        case=case,
        assignee=intern,
        reviewer=lawyer,
        due_date=timezone.localdate() + dt.timedelta(days=5),
        created_by=lawyer,
    )
    hearing = Hearing.objects.create(
        case=case,
        starts_at=timezone.now() + dt.timedelta(days=3),
        created_by=lawyer,
    )
    doc = Document(case=case, title="gizli.pdf", original_name="gizli.pdf")
    doc.file.save("gizli.pdf", ContentFile(b"%PDF-1.4"), save=False)
    doc.save()
    return {"case": case, "task": task, "hearing": hearing, "doc": doc}


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def case_endpoints(case, task, hearing):
    """(yöntem, url, veri) — dosya, görev ve duruşma uçları."""
    return [
        ("get", reverse("tasks:detail", args=[task.pk]), None),
        ("get", reverse("tasks:update", args=[task.pk]), None),
        ("post", reverse("tasks:note", args=[task.pk]), {"note": "sızma"}),
        ("post", reverse("tasks:comment", args=[task.pk]), {"comment": "sızma"}),
        ("post", reverse("tasks:action", args=[task.pk]), {"action": "close"}),
        ("post", reverse("tasks:delete", args=[task.pk]), None),
        ("post", reverse("tasks:doc_upload", args=[task.pk]), None),
        ("get", reverse("tasks:petition_template", args=[task.pk]), None),
        ("get", reverse("cases:detail", args=[case.pk]), None),
        ("post", reverse("cases:hearing_add", args=[case.pk]), {"starts_at": "2026-12-01T10:00"}),
        (
            "post",
            reverse("cases:hearing_result", args=[case.pk, hearing.pk]),
            {"status": "done", "result": "sızma"},
        ),
        ("post", reverse("cases:event_add", args=[case.pk]), {"title": "sızma"}),
        ("get", reverse("hearings:edit", args=[hearing.pk]), None),
        ("get", reverse("hearings:result", args=[hearing.pk]), None),
        ("get", reverse("hearings:task_create", args=[hearing.pk]), None),
    ]


def test_outsider_gets_404_on_case_task_and_hearing_endpoints(owned, outsider):
    c = login(outsider)
    before_events = TaskEvent.objects.count()
    before_hearings = Hearing.objects.count()
    for method, url, data in case_endpoints(owned["case"], owned["task"], owned["hearing"]):
        send = getattr(c, method)
        response = send(url, data or {})
        assert response.status_code == 404, f"{method.upper()} {url} -> {response.status_code}"
    assert TaskEvent.objects.count() == before_events
    assert Hearing.objects.count() == before_hearings
    assert Task.objects.filter(pk=owned["task"].pk).exists()


def test_outsider_cannot_see_task_in_task_list_or_case_options(owned, outsider):
    c = login(outsider)
    r = c.get(reverse("tasks:list"), {"kapsam": "tumu", "sekme": "aktif"})
    assert r.status_code == 200
    assert "Gizli görev" not in r.content.decode()

    r = c.get(reverse("tasks:case_options"), {"id": owned["case"].pk})
    assert r.json()["cases"] == []


def test_outsider_cannot_open_case_via_task_create_prefill(owned, outsider):
    r = login(outsider).get(reverse("tasks:create"), {"dosya": owned["case"].pk})
    assert r.status_code == 200
    assert r.context["form"].initial.get("case") is None


def test_task_form_offers_only_visible_cases_to_outsider(owned, outsider, case_factory):
    from apps.tasks.forms import TaskForm

    own_visible = case_factory(
        client=owned["case"].client,
        responsible_lawyer=outsider,
        responsible_intern=None,
    )
    form = TaskForm(user=outsider)
    allowed = set(form.fields["case"].queryset.values_list("pk", flat=True))
    assert own_visible.pk in allowed
    assert owned["case"].pk not in allowed


def test_outsider_cannot_create_task_on_hidden_case(owned, outsider):
    from apps.tasks.forms import TaskForm

    form = TaskForm(
        data={
            "task_type": TaskType.objects.get(name="Müvekkil Görüşmesi").pk,
            "title": "Sızma",
            "case": owned["case"].pk,
            "assignee": outsider.pk,
            "reviewer": outsider.pk,
            "due_date": "2026-12-20",
        },
        user=outsider,
    )
    assert not form.is_valid()
    assert "case" in form.errors


def test_responsible_lawyer_and_admin_keep_access(owned, lawyer, admin_user):
    for user in (lawyer, admin_user):
        c = login(user)
        r = c.get(reverse("tasks:detail", args=[owned["task"].pk]))
        assert r.status_code == 200
        r = c.get(reverse("cases:detail", args=[owned["case"].pk]))
        assert r.status_code == 200
        r = c.get(reverse("hearings:result", args=[owned["hearing"].pk]))
        assert r.status_code == 200


def test_assignee_of_task_keeps_access_to_that_task(owned, intern):
    """Dosyası görünmese bile kendisine atanmış göreve erişebilir."""
    r = login(intern).get(reverse("tasks:detail", args=[owned["task"].pk]))
    assert r.status_code == 200


def test_public_mode_allows_outsider(owned, outsider):
    office = OfficeSettings.load()
    office.case_visibility_mode = OfficeSettings.CaseVisibilityMode.PUBLIC
    office.save(update_fields=["case_visibility_mode"])
    r = login(outsider).get(reverse("tasks:detail", args=[owned["task"].pk]))
    assert r.status_code == 200


def test_outsider_cannot_download_case_document(owned, outsider):
    url = owned["doc"].file.url
    r = login(outsider).get(url)
    assert r.status_code == 403


def test_responsible_lawyer_can_download_case_document(owned, lawyer):
    r = login(lawyer).get(owned["doc"].file.url)
    assert r.status_code == 200


def test_reports_exclude_hidden_cases_and_tasks(owned, outsider, lawyer):
    from apps.reports.definitions import build_cases, build_client_cases, build_tasks

    assert build_cases({}, outsider).rows == []
    assert build_tasks({}, outsider).rows == []
    assert build_client_cases({}, outsider).rows == []

    assert len(build_cases({}, lawyer).rows) == 1
    assert len(build_tasks({}, lawyer).rows) == 1
    assert len(build_client_cases({}, lawyer).rows) == 1


def test_report_seizures_exclude_hidden_enforcement_case(owned, outsider):
    from apps.reports.definitions import build_seizures

    enforcement = Case.objects.create(
        client=owned["case"].client,
        case_type=CaseType.ENFORCEMENT,
        subject="İcra",
        responsible_lawyer=owned["case"].responsible_lawyer,
        responsible_intern=owned["case"].responsible_intern,
    )
    Seizure.objects.create(
        case=enforcement,
        debtor="Borçlu",
        is_active=True,
        created_by=owned["case"].responsible_lawyer,
    )
    assert build_seizures({}, outsider).rows == []
    assert len(build_seizures({}, make_user("yonetici2", User.Role.ADMIN)).rows) == 1


def test_hearing_list_hides_hidden_case_hearings(owned, outsider):
    r = login(outsider).get(reverse("hearings:list"), {"scope": "upcoming"})
    assert r.status_code == 200
    assert owned["hearing"] not in list(r.context["hearings"])
