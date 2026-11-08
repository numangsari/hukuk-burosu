import datetime as dt

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
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
            "task_type": TaskType.objects.get(name="Müvekkil Görüşmesi"),  # belge zorunlu değil
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
            "requires_accounting": "yes",
        },
    )
    assert r.status_code == 302
    t = Task.objects.get()
    assert t.client_id == case.client_id and t.created_by == lawyer
    assert t.events.get().kind == "created"
    assert not t.assignee_seen  # avukat stajyere atadı: "Yeni görev"


@pytest.mark.parametrize(("choice", "expected"), [("yes", True), ("no", False)])
def test_task_accounting_choice_is_saved(lawyer, intern, case_factory, choice, expected):
    case = case_factory()
    response = login(lawyer).post(
        reverse("tasks:create"),
        {
            "task_type": TaskType.objects.first().pk,
            "title": "Örnek görev",
            "case": case.pk,
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "due_date": "2026-11-10",
            "requires_accounting": choice,
        },
    )
    assert response.status_code == 302
    assert Task.objects.get().requires_accounting is expected


def test_task_types_are_grouped_and_searchable(lawyer):
    response = login(lawyer).get(reverse("tasks:create"))
    html = response.content.decode()
    assert 'data-searchable="Görev türü ara"' in html
    assert '<optgroup label="Dava İşlemleri">' in html
    assert '<optgroup label="Ceza ve Soruşturma İşlemleri">' in html
    assert '<optgroup label="Ofis İçi İşlemler">' in html
    assert 'label="Ofis İçi, Araştırma ve Diğer İşlemler"' not in html
    assert html.count(">İstinaf Dilekçesi</option>") == 1


def test_task_type_capitalizes_turkish_word_initials():
    task_type = TaskType.objects.create(name="icra işlemi / ıslah (iade) E-SMM")
    task_type.refresh_from_db()
    assert task_type.name == "İcra İşlemi / Islah (İade) E-SMM"


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
    services.perform(t, "submit", intern, "Not")
    assert t.status == TaskStatus.REVIEW
    assert t.stage_label == "Kontrolde"

    with pytest.raises(ValidationError):
        services.perform(t, "revise", lawyer, "")  # açıklama zorunlu
    services.perform(t, "revise", lawyer, "Emsal kararları ekle")
    assert t.status == TaskStatus.ACTIVE and t.revision_requested
    assert t.stage_label == "Revize İstendi"

    services.perform(t, "submit", intern, "Not")
    assert t.stage_label == "Revize Edildi"
    services.perform(t, "approve", lawyer)
    t.refresh_from_db()
    assert t.status == TaskStatus.ACTIVE and t.completed_at is None
    assert t.stage_label == "Onaylandı"
    assert CaseEvent.objects.filter(case=t.case, kind="task").exists()
    kinds = list(t.events.order_by("created_at", "pk").values_list("kind", flat=True))
    assert kinds == ["submitted", "revision", "submitted", "approved"]

    with pytest.raises(PermissionDenied):
        services.perform(t, "submit", intern, "Not")


def test_permissions(task_factory, lawyer, intern, admin_user):
    t = task_factory()
    with pytest.raises(PermissionDenied):
        services.perform(t, "submit", lawyer, "Not")  # kontrolcü kontrole gönderemez
    services.perform(t, "submit", intern, "Not")
    with pytest.raises(PermissionDenied):
        services.perform(t, "approve", intern)  # sorumlu kendi işini onaylayamaz
    with pytest.raises(ValidationError):
        services.perform(t, "cancel", lawyer)  # iptal işlemi yok
    with pytest.raises(PermissionDenied):
        services.perform(t, "approve", admin_user)  # yönetici kontrolcü değilse onaylayamaz
    services.perform(t, "approve", lawyer)
    assert t.status == TaskStatus.ACTIVE and t.stage_label == "Onaylandı"
    assert services.available_actions(t, lawyer) == []
    assert [a.key for a in services.available_actions(t, intern)] == ["close"]


def test_close_reopen_and_points(task_factory, lawyer, intern, admin_user):
    task = task_factory()
    with pytest.raises(PermissionDenied):
        services.perform(task, "close", intern, "Bitti")
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    with pytest.raises(ValidationError):
        services.perform(task, "close", intern)
    services.perform(task, "close", intern, "İş tamamlandı")
    assert task.status == TaskStatus.DONE
    assert task.events.filter(kind="closed", comment="İş tamamlandı").exists()
    assert task.points_awarded.count() == 2
    with pytest.raises(PermissionDenied):
        services.perform(task, "reopen", intern)
    services.perform(task, "reopen", lawyer)
    assert task.status == TaskStatus.ACTIVE
    assert not task.points_awarded.exists()
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    services.perform(task, "close", intern, "Yeniden tamamlandı")
    assert task.points_awarded.count() == 2
    services.perform(task, "reopen", admin_user)
    assert not task.points_awarded.exists()


def test_close_requires_related_accounting_entry(task_factory, intern, lawyer, case_factory):
    from apps.accounting.models import LedgerEntry

    task = task_factory(requires_accounting=True)
    other = case_factory()
    unrelated = LedgerEntry.objects.create(
        client=other.client, case=other, kind="expense", amount=10, date=timezone.localdate()
    )
    entry = LedgerEntry.objects.create(
        client=task.client, case=task.case, kind="expense", amount=20, date=timezone.localdate()
    )
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    for value in ("", str(unrelated.pk)):
        with pytest.raises(ValidationError):
            services.perform(task, "close", intern, "Bitti", value)
    services.perform(task, "close", intern, "Bitti", str(entry.pk))
    assert task.status == TaskStatus.DONE
    assert task.events.filter(comment__contains=f"Gelir/gider kaydı: {entry.pk}").exists()


def test_close_requires_petition_and_shows_result(task_factory, intern, lawyer):
    task = task_factory()
    services.perform(task, "submit", intern, "Not")
    services.perform(task, "approve", lawyer)
    task.task_type.requires_document = True
    task.task_type.save(update_fields=["requires_document"])
    with pytest.raises(ValidationError):
        services.perform(task, "close", intern, "Tamamlandı")
    task.task_type.requires_document = False
    task.task_type.save(update_fields=["requires_document"])
    response = login(intern).post(
        reverse("tasks:action", args=[task.pk]), {"action": "close", "comment": "Tamamlandı"}
    )
    assert response.status_code == 302
    assert "Tamamlandı" in login(intern).get(task.get_absolute_url()).content.decode()


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
    # Görev notu olmadan kontrole gönderilemez.
    c.post(reverse("tasks:action", args=[t.pk]), {"action": "submit"})
    t.refresh_from_db()
    assert t.status == TaskStatus.ACTIVE
    c.post(reverse("tasks:action", args=[t.pk]), {"action": "submit", "comment": "Hazır"})
    t.refresh_from_db()
    assert t.status == TaskStatus.REVIEW
    assert t.events.get(kind="submitted").comment == "Hazır"
    r = c.post(reverse("tasks:action", args=[t.pk]), {"action": "approve"})
    assert r.status_code == 403


def test_comment_is_recorded(task_factory, intern):
    t = task_factory()
    login(intern).post(reverse("tasks:comment", args=[t.pk]), {"comment": "Dosya eksik"})
    assert t.events.filter(kind="comment").exists()


def test_task_list_scopes(task_factory, intern, lawyer):
    task_factory(title="A")
    t2 = task_factory(title="B")
    services.perform(t2, "submit", intern, "Not")
    c = login(lawyer)
    titles = lambda r: [t.title for t in r.context["tasks"]]  # noqa: E731
    assert titles(c.get(reverse("tasks:list"), {"sekme": "bekleyen"})) == ["B"]
    assert titles(c.get(reverse("tasks:list"), {"kapsam": "bana"})) == []
    assert titles(login(intern).get(reverse("tasks:list"))) == ["A"]
    assert titles(login(intern).get(reverse("tasks:list"), {"sekme": "kontrolde"})) == ["B"]
    assert titles(c.get(reverse("tasks:list"), {"kapsam": "tumu", "sekme": "bekleyen"})) == ["B"]


def test_closed_tasks_scope_includes_both_roles(task_factory, lawyer, intern):
    closed = task_factory(title="Kapalı iş", status=TaskStatus.DONE)
    for user in (lawyer, intern):
        response = login(user).get(reverse("tasks:list"), {"sekme": "kapali"})
        assert [task.pk for task in response.context["tasks"]] == [closed.pk]
        assert "Kapalı" in response.content.decode()


def test_points_for_closed_task_are_recorded_once(task_factory, lawyer, intern, admin_user):
    from apps.tasks.models import TaskPoint

    task = task_factory()
    task.task_type.points = 3
    task.task_type.save(update_fields=["points"])
    with pytest.raises(ValidationError):
        services.award_closed_task_points(task)
    task.status = TaskStatus.DONE
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at"])
    services.award_closed_task_points(task)
    services.award_closed_task_points(task)
    assert set(TaskPoint.objects.values_list("user_id", "points")) == {
        (intern.pk, 3),
        (lawyer.pk, 3),
    }
    task.task_type.points = 1
    task.task_type.save(update_fields=["points"])
    services.award_closed_task_points(task)
    assert list(TaskPoint.objects.values_list("points", flat=True)) == [3, 3]
    report = login(admin_user).get(reverse("accounts:settings"), {"bolum": "puanlar"})
    rows = {person.pk: person for person in report.context["point_users"]}
    assert rows[intern.pk].week_points == rows[lawyer.pk].month_points == 3
    assert (
        "point_users"
        not in login(intern).get(reverse("accounts:settings"), {"bolum": "puanlar"}).context
    )

    # use_task_points=False durumunda puan verilmez
    from apps.office.models import OfficeSettings

    office = OfficeSettings.load()
    office.use_task_points = False
    office.save(update_fields=["use_task_points"])
    TaskPoint.objects.all().delete()
    services.award_closed_task_points(task)
    assert TaskPoint.objects.count() == 0


def test_tab_counts_follow_scope_and_filters(task_factory, lawyer, intern):
    task_factory(title="Aranan aktif")
    review = task_factory(title="Aranan kontrol")
    services.perform(review, "submit", intern, "Not")
    task_factory(title="Başka görev", status=TaskStatus.DONE)
    url = reverse("tasks:list")
    response = login(intern).get(url, {"q": "Aranan"}, HTTP_HX_REQUEST="true")
    counts = {key: count for key, _, count in response.context["tabs"]}
    assert counts == {"aktif": 1, "bekleyen": 0, "kontrolde": 1, "kapali": 0}
    assert 'hx-swap-oob="outerHTML"' in response.content.decode()
    response = login(lawyer).get(url, {"kapsam": "tumu"})
    counts = {key: count for key, _, count in response.context["tabs"]}
    assert counts == {"aktif": 1, "bekleyen": 1, "kontrolde": 1, "kapali": 1}


def test_home_active_tasks_sorted_by_urgency(task_factory, intern, lawyer):
    today = timezone.localdate()
    task_factory(title="Sonra", due_date=today + dt.timedelta(days=10))
    task_factory(title="Gecikmiş", due_date=today - dt.timedelta(days=2))
    review = task_factory(title="Kontrolde", due_date=today)
    services.perform(review, "submit", intern, "Not")
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
    services.perform(t, "submit", intern, "Not")
    services.perform(t, "revise", lawyer, comment="Ek delilleri ekleyin")
    c = login(intern)
    r = c.get(reverse("core:home"))
    row = r.context["own_tasks"][0]
    assert row.revision_note == "Ek delilleri ekleyin"
    assert "Ek delilleri ekleyin" in r.content.decode()

    services.perform(t, "submit", intern, "Not")
    services.perform(t, "approve", lawyer)
    r = c.get(reverse("core:home"))
    # Onaylanan görev sorumluya "Onaylandı" olarak döner.
    assert [x.title for x in r.context["approved_tasks"]] == ["DİLEKÇE"]
    assert "Onaylandı" in r.content.decode()
    # Görevi açmak onay satırını kaldırmaz (tamamlama prosedürü ayrıca belirlenecek).
    c.get(t.get_absolute_url())
    assert list(c.get(reverse("core:home")).context["approved_tasks"]) != []
    # Kapatma işlemi tanımlanana kadar onaylanan görev aktif kalır.
    t.refresh_from_db()
    assert t.status == TaskStatus.ACTIVE and t.stage_label == "Onaylandı"


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
    services.perform(t, "submit", intern, "Not")
    services.perform(t, "revise", lawyer, comment="Düzeltin")
    other = make_user("stajyer2", "intern")
    old = t.assignee_id
    t.assignee = other
    t.save()
    services.on_updated(t, lawyer, ["Sorumlu"], old)
    t.refresh_from_db()
    assert not t.assignee_seen and not t.revision_requested


def test_submit_only_assignee(task_factory, admin_user, lawyer, intern):
    t = task_factory(title="Yetki")
    assert "submit" not in [a.key for a in services.available_actions(t, lawyer)]  # kontrolcü
    assert "submit" not in [a.key for a in services.available_actions(t, admin_user)]
    assert "submit" in [a.key for a in services.available_actions(t, intern)]


def test_own_task_is_new_until_opened(task_factory, intern):
    t = task_factory(title="Kendi işim")
    services.on_created(t, intern)  # stajyer kendine görev açtı
    t.refresh_from_db()
    assert not t.assignee_seen
    login(intern).get(t.get_absolute_url())
    t.refresh_from_db()
    assert t.assignee_seen


def test_due_labels(task_factory):
    today = timezone.localdate()
    assert task_factory(due_date=today - dt.timedelta(days=3)).due_label == "3 gün gecikti"
    assert task_factory(due_date=today).urgency == "today"
    assert task_factory(due_date=today + dt.timedelta(days=1)).due_label == "Yarın"


def test_task_modal_save_returns_same_site_completion(lawyer, intern, case_factory):
    case = case_factory()
    response = login(lawyer).post(
        reverse("tasks:create") + "?pencere=1",
        {
            "task_type": TaskType.objects.first().pk,
            "title": "Örnek görev",
            "case": case.pk,
            "assignee": intern.pk,
            "reviewer": lawyer.pk,
            "due_date": "2026-11-10",
            "requires_accounting": "no",
        },
    )
    assert response.status_code == 200
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert b"window.parent.location.reload()" in response.content
    assert Task.objects.filter(case=case).exists()


def test_marked_task_types_require_document():
    assert TaskType.objects.get(name="Dava Dilekçesi Hazırlama Ve Dava Açılışı").requires_document
    assert TaskType.objects.get(name="Delil Sunma").requires_document
    assert not TaskType.objects.get(name="Dava Dosyası İnceleme").requires_document


def test_only_creator_admin_and_senior_can_edit_task(task_factory, lawyer, intern, admin_user):
    from .conftest import make_user

    senior = make_user("kidemli2", User.Role.SENIOR)
    task = task_factory(assignee=intern, reviewer=lawyer, created_by=intern)
    url = reverse("tasks:update", args=[task.pk])
    assert login(lawyer).get(url).status_code == 403  # kontrolcü bile düzenleyemez
    assert login(intern).get(url).status_code == 200  # oluşturan
    assert login(admin_user).get(url).status_code == 200
    assert login(senior).get(url).status_code == 200
    other = task_factory(assignee=intern, reviewer=lawyer, created_by=admin_user)
    assert login(intern).get(reverse("tasks:update", args=[other.pk])).status_code == 403


def test_inline_edit_returns_form_fragment_and_redirects(task_factory, lawyer, intern, admin_user):
    task = task_factory(assignee=intern, reviewer=lawyer, created_by=admin_user)
    url = reverse("tasks:update", args=[task.pk]) + "?pencere=1"
    page = login(admin_user).get(url, HTTP_HX_REQUEST="true")
    assert page.status_code == 200
    assert b"<html" not in page.content and b'id="task-form"' in page.content
    detail = login(admin_user).get(task.get_absolute_url() + "?pencere=1").content.decode()
    assert "task-edit-slot" in detail
    assert "task-edit-slot" in login(admin_user).get(task.get_absolute_url()).content.decode()
    hidden = login(lawyer).get(task.get_absolute_url() + "?pencere=1").content.decode()
    assert 'hx-get="' + reverse("tasks:update", args=[task.pk]) not in hidden  # düzenle butonu yok


def test_task_notes_are_separate_and_record_author(task_factory, lawyer, intern):
    task = task_factory(notes="Önceki not")
    url = reverse("tasks:note", args=[task.pk])
    login(lawyer).post(url, {"note": "İlk yeni not"})
    login(intern).post(url, {"note": "İkinci yeni not"})
    response = login(lawyer).get(task.get_absolute_url() + "?pencere=1")
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert [note.comment for note in response.context["notes"]] == [
        "İkinci yeni not",
        "İlk yeni not",
    ]
    assert [note.actor for note in response.context["notes"]] == [intern, lawyer]
    task.refresh_from_db()
    assert task.notes == "Önceki not"


def test_document_and_accounting_follow_type_unless_task_overrides(task_factory):
    doc_type = TaskType.objects.filter(requires_document=True, is_active=True).first()
    t = task_factory(task_type=doc_type)
    assert t.needs_document is True  # seçim yoksa türün varsayılanı
    t.requires_document = False
    assert t.needs_document is False  # oluşturan görev başına değiştirebilir
    t.requires_document = True
    t.task_type = TaskType.objects.get(name="Müvekkil Görüşmesi")
    assert t.needs_document is True
    t.requires_accounting = None
    assert t.needs_accounting is False
    t.requires_accounting = True
    assert t.needs_accounting is True


def test_submit_respects_task_level_document_choice(task_factory, intern):
    doc_type = TaskType.objects.filter(requires_document=True, is_active=True).first()
    required = task_factory(task_type=doc_type, requires_document=None)
    with pytest.raises(ValidationError):
        services.perform(required, "submit", intern, "Not")
    waived = task_factory(task_type=doc_type, requires_document=False)
    services.perform(waived, "submit", intern, "Not")  # oluşturan dilekçeyi zorunlu tutmadı
    assert waived.status == TaskStatus.REVIEW


def test_task_form_has_document_choice_and_keeps_creator_override(
    admin_user, lawyer, intern, case_factory
):
    doc_type = TaskType.objects.filter(requires_document=True, is_active=True).first()
    case = case_factory()
    data = {
        "task_type": doc_type.pk,
        "title": "Deneme",
        "case": case.pk,
        "assignee": intern.pk,
        "reviewer": lawyer.pk,
        "due_date": (timezone.localdate() + dt.timedelta(days=3)).isoformat(),
        "requires_accounting": "no",
        "requires_document": "no",
    }
    page = login(admin_user).get(reverse("tasks:create")).content.decode()
    assert 'name="requires_document"' in page and "Dilekçe zorunluluğu" in page
    r = login(admin_user).post(reverse("tasks:create"), data)
    assert r.status_code == 302
    task = Task.objects.get(title="DENEME")
    assert task.requires_document is False and task.requires_accounting is False
    assert task.needs_document is False


def test_home_review_panels_follow_role(task_factory, admin_user, lawyer, intern):
    from .conftest import make_user

    senior = make_user("kidemli4", User.Role.SENIOR)
    task = task_factory(assignee=intern, reviewer=lawyer)
    services.perform(task, "submit", intern, "Hazır")
    own = task_factory(assignee=lawyer, reviewer=senior, title="Avukatın görevi")
    services.perform(own, "submit", lawyer, "Hazır")

    def home(user):
        return login(user).get(reverse("core:home")).context

    ctx = home(lawyer)
    assert ctx["show_review"] and ctx["show_submitted"]
    assert [t.pk for t in ctx["review_tasks"]] == [task.pk]  # kontrolümü bekleyen
    assert [t.pk for t in ctx["submitted_tasks"]] == [own.pk]  # kontrolde olan
    ctx = home(senior)
    assert ctx["show_review"] and ctx["show_submitted"]
    assert [t.pk for t in ctx["review_tasks"]] == [own.pk]
    ctx = home(admin_user)
    assert ctx["show_review"] and not ctx["show_submitted"]
    ctx = home(intern)
    assert not ctx["show_review"] and ctx["show_submitted"]
    assert [t.pk for t in ctx["submitted_tasks"]] == [task.pk]
    assert "Kontrolde olanlar" in login(intern).get(reverse("core:home")).content.decode()


def test_admin_cannot_be_assignee_and_intern_cannot_be_reviewer(
    admin_user, lawyer, intern, case_factory
):
    from apps.tasks.forms import TaskForm

    form = TaskForm(user=admin_user)
    assignees = set(form.fields["assignee"].queryset)
    reviewers = set(form.fields["reviewer"].queryset)
    assert admin_user not in assignees and lawyer in assignees and intern in assignees
    assert intern not in reviewers and intern not in set(form.fields["second_reviewer"].queryset)
    assert admin_user in reviewers and lawyer in reviewers
    # Sunucu tarafı: elle gönderilen yönetici sorumlu / stajyer kontrolcü reddedilir.
    data = {
        "task_type": TaskType.objects.first().pk,
        "title": "Rol denemesi",
        "case": case_factory().pk,
        "assignee": admin_user.pk,
        "reviewer": intern.pk,
        "due_date": (timezone.localdate() + dt.timedelta(days=3)).isoformat(),
        "requires_accounting": "no",
    }
    r = login(admin_user).post(reverse("tasks:create"), data)
    errors = r.context["form"].errors
    assert "assignee" in errors and "reviewer" in errors
    assert not Task.objects.exists()
