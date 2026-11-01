import datetime as dt

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import CaseEvent
from apps.office.models import TaskType
from apps.tasks import services
from apps.tasks.models import Task, TaskStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def task_factory(case_factory, lawyer, intern):
    def factory(**kw):
        case = kw.pop("case", None) or case_factory()
        defaults = {
            "task_type": TaskType.objects.get(name="Müvekkil görüşmesi"),  # belge zorunlu değil
            "title": "Cevap dilekçesi hazırla",
            "case": case,
            "assignee": intern,
            "reviewer": lawyer,
            "due_date": timezone.localdate() + dt.timedelta(days=5),
            "created_by": lawyer,
        }
        defaults.update(kw)
        return Task.objects.create(**defaults)

    return factory


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


def test_client_always_follows_case(task_factory, client_factory, case_factory):
    other = client_factory(first_name="Başka")
    t = task_factory(case=case_factory(client=other))
    assert t.client == other


def test_create_task_via_form_notifies_assignee(lawyer, intern, case_factory):
    case = case_factory()
    r = login(lawyer).post(
        reverse("tasks:create"),
        {
            "task_type": TaskType.objects.first().pk,
            "title": "Bilirkişi raporuna itiraz",
            "client": case.client_id,
            "case": case.pk,
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "due_date": "2026-11-10",
        },
    )
    assert r.status_code == 302
    t = Task.objects.get()
    assert t.client_id == case.client_id and t.created_by == lawyer
    assert t.events.get().kind == "created"
    assert not t.assignee_seen  # avukat stajyere atadı: "Yeni görev"


def test_form_rejects_same_assignee_reviewer_and_wrong_client(lawyer, case_factory, client_factory):
    case = case_factory()
    other = client_factory(first_name="Diğer")
    r = login(lawyer).post(
        reverse("tasks:create"),
        {
            "task_type": TaskType.objects.first().pk,
            "title": "x",
            "client": other.pk,
            "case": case.pk,
            "assignee": lawyer.pk,
            "reviewer": lawyer.pk,
            "due_date": "2026-11-10",
        },
    )
    errors = r.context["form"].errors
    assert "reviewer" in errors and "case" in errors
    assert not Task.objects.exists()


def test_full_approval_cycle(task_factory, lawyer, intern):
    t = task_factory()
    assert t.status == TaskStatus.ACTIVE  # oluşturulunca doğrudan aktif
    services.perform(t, "submit", intern)
    assert t.status == TaskStatus.REVIEW

    with pytest.raises(ValidationError):
        services.perform(t, "revise", lawyer, "")  # açıklama zorunlu
    services.perform(t, "revise", lawyer, "Emsal kararları ekle")
    assert t.status == TaskStatus.ACTIVE and t.revision_requested

    services.perform(t, "submit", intern)
    assert not t.revision_requested
    services.perform(t, "approve", lawyer)
    t.refresh_from_db()
    assert t.status == TaskStatus.DONE and t.completed_at
    assert CaseEvent.objects.filter(case=t.case, kind="task").exists()
    kinds = list(t.events.order_by("created_at", "pk").values_list("kind", flat=True))
    assert kinds == ["submitted", "revision", "submitted", "approved"]

    services.perform(t, "reopen", lawyer)
    assert t.status == TaskStatus.ACTIVE and t.completed_at is None


def test_permissions(task_factory, lawyer, intern, admin_user):
    t = task_factory()
    with pytest.raises(PermissionDenied):
        services.perform(t, "submit", lawyer)  # kontrolcü kontrole gönderemez
    services.perform(t, "submit", intern)
    with pytest.raises(PermissionDenied):
        services.perform(t, "approve", intern)  # sorumlu kendi işini onaylayamaz
    with pytest.raises(ValidationError):
        services.perform(t, "cancel", lawyer)  # iptal işlemi yok
    services.perform(t, "approve", admin_user)  # yönetici her işlemi yapabilir
    assert t.status == TaskStatus.DONE
    assert [a.key for a in services.available_actions(t, lawyer)] == ["reopen"]
    assert services.available_actions(t, intern) == []


def test_delete_only_creator_or_admin(task_factory, lawyer, intern):
    t = task_factory()  # oluşturan: lawyer
    assert login(intern).post(reverse("tasks:delete", args=[t.pk])).status_code == 403
    r = login(lawyer).post(reverse("tasks:delete", args=[t.pk]))
    assert r.status_code == 302 and not Task.objects.exists()


def test_action_endpoint_and_detail(task_factory, intern):
    t = task_factory()
    c = login(intern)
    r = c.get(t.get_absolute_url())
    assert [a.key for a in r.context["actions"]] == ["submit"]
    assert "İşe başla" not in r.content.decode()
    c.post(reverse("tasks:action", args=[t.pk]), {"action": "submit"})
    t.refresh_from_db()
    assert t.status == TaskStatus.REVIEW
    r = c.post(reverse("tasks:action", args=[t.pk]), {"action": "approve"})
    assert r.status_code == 403


def test_comment_is_recorded(task_factory, intern):
    t = task_factory()
    login(intern).post(reverse("tasks:comment", args=[t.pk]), {"comment": "Dosya eksik"})
    assert t.events.filter(kind="comment").exists()


def test_task_list_scopes(task_factory, intern, lawyer):
    task_factory(title="A")
    t2 = task_factory(title="B")
    services.perform(t2, "submit", intern)
    c = login(lawyer)
    titles = lambda r: [t.title for t in r.context["tasks"]]  # noqa: E731
    assert titles(c.get(reverse("tasks:list"), {"kapsam": "kontrol"})) == ["A", "B"]
    assert titles(c.get(reverse("tasks:list"), {"kapsam": "bana"})) == []
    assert titles(login(intern).get(reverse("tasks:list"))) == ["A", "B"]


def test_home_active_tasks_sorted_by_urgency(task_factory, intern, lawyer):
    today = timezone.localdate()
    task_factory(title="Sonra", due_date=today + dt.timedelta(days=10))
    task_factory(title="Gecikmiş", due_date=today - dt.timedelta(days=2))
    review = task_factory(title="Kontrolde", due_date=today)
    services.perform(review, "submit", intern)
    r = login(intern).get(reverse("core:home"))
    # Kontrole gönderilen görev sorumlunun listesinden çıkar.
    assert [t.title for t in r.context["own_tasks"]] == ["GECİKMİŞ", "SONRA"]
    # Stajyerde kontrol paneli gösterilmez.
    assert not r.context["show_review"]
    assert "Kontrolümü bekleyenler" not in r.content.decode()
    r = login(lawyer).get(reverse("core:home"))
    # Kontrolcüde ayrı bölümde görünür, kendi görevleriyle karışmaz.
    assert list(r.context["own_tasks"]) == []
    assert [t.title for t in r.context["review_tasks"]] == ["KONTROLDE"]
    assert "Kontrolümü bekleyenler" in r.content.decode()


def test_home_shows_revision_note_and_approval_until_seen(task_factory, intern, lawyer):
    t = task_factory(title="Dilekçe")
    services.perform(t, "submit", intern)
    services.perform(t, "revise", lawyer, comment="Ek delilleri ekleyin")
    c = login(intern)
    r = c.get(reverse("core:home"))
    row = r.context["own_tasks"][0]
    assert row.revision_note == "Ek delilleri ekleyin"
    assert "Ek delilleri ekleyin" in r.content.decode()

    services.perform(t, "submit", intern)
    services.perform(t, "approve", lawyer)
    r = c.get(reverse("core:home"))
    # Onaylanan görev sorumluya "Onaylandı" olarak döner.
    assert [x.title for x in r.context["approved_tasks"]] == ["DİLEKÇE"]
    assert "Onaylandı" in r.content.decode()
    # Görevi açmak onay satırını kaldırmaz (tamamlama prosedürü ayrıca belirlenecek).
    c.get(t.get_absolute_url())
    assert list(c.get(reverse("core:home")).context["approved_tasks"]) != []
    # Yeniden açılınca onay satırı kalkar.
    services.perform(t, "reopen", lawyer)
    assert list(c.get(reverse("core:home")).context["approved_tasks"]) == []


def test_new_task_flag_until_assignee_opens(task_factory, intern, lawyer):
    t = task_factory(title="Yeni iş")
    services.on_created(t, lawyer)  # avukat stajyere atadı
    c = login(intern)
    r = c.get(reverse("core:home"))
    assert not r.context["own_tasks"][0].assignee_seen
    assert "chip-solid-new" in r.content.decode()
    # Kontrolcünün açması uyarıyı kaldırmaz, sorumlunun açması kaldırır.
    login(lawyer).get(t.get_absolute_url())
    t.refresh_from_db()
    assert not t.assignee_seen
    c.get(t.get_absolute_url())
    t.refresh_from_db()
    assert t.assignee_seen
    assert "chip-solid-new" not in c.get(reverse("core:home")).content.decode()


def test_reassigned_task_is_new_not_revision(task_factory, intern, lawyer):
    from tests.conftest import make_user

    t = task_factory(title="Devir")
    services.perform(t, "submit", intern)
    services.perform(t, "revise", lawyer, comment="Düzeltin")
    other = make_user("stajyer2", "intern")
    old = t.assignee_id
    t.assignee = other
    t.save()
    services.on_updated(t, lawyer, ["Sorumlu"], old)
    t.refresh_from_db()
    assert not t.assignee_seen and not t.revision_requested


def test_submit_only_assignee_or_admin(task_factory, admin_user, lawyer):
    t = task_factory(title="Yetki")
    assert "submit" not in [a.key for a in services.available_actions(t, lawyer)]  # kontrolcü
    assert "submit" in [a.key for a in services.available_actions(t, admin_user)]


def test_own_task_is_not_marked_new(task_factory, intern):
    t = task_factory(title="Kendi işim")
    services.on_created(t, intern)  # stajyer kendine görev açtı
    t.refresh_from_db()
    assert t.assignee_seen


def test_due_labels(task_factory):
    today = timezone.localdate()
    assert task_factory(due_date=today - dt.timedelta(days=3)).due_label == "3 gün gecikti"
    assert task_factory(due_date=today).urgency == "today"
    assert task_factory(due_date=today + dt.timedelta(days=1)).due_label == "Yarın"
