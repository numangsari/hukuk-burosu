import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.accounts.models import User
from apps.office.models import OfficeSettings

pytestmark = pytest.mark.django_db

TEST_PIN = "4826"  # yalnızca test için uydurma PIN


@pytest.fixture
def pin_user(db):
    u = User.objects.create_user(
        username="test.kullanici", first_name="Test", last_name="KULLANICI", title="Avukat"
    )
    u.set_password(TEST_PIN)
    u.save()
    return u


def test_login_page_lists_active_users_only(client, pin_user):
    User.objects.create_user(username="pasif", first_name="Pasif", is_active=False)
    r = client.get(reverse("accounts:login"))
    assert list(r.context["users"]) == [pin_user]
    assert 'data-username="test.kullanici"' in r.content.decode()


def test_login_with_pin(client, pin_user):
    r = client.post(
        reverse("accounts:login"), {"username": pin_user.username, "password": TEST_PIN}
    )
    assert r.status_code == 302
    assert r.url == reverse("core:home")


def test_logged_in_pages_are_not_stored_and_logout_ends_session(client, pin_user):
    client.force_login(pin_user)
    r = client.get(reverse("core:home"))
    assert r.status_code == 200
    assert "no-store" in r["Cache-Control"]
    client.post(reverse("accounts:logout"))
    # Geri tuşu sunucuya yeniden sorduğunda eski sayfa değil giriş ekranı gelir.
    r = client.get(reverse("core:home"))
    assert r.status_code == 302
    assert r.url.startswith(reverse("accounts:login"))


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def test_login_is_throttled_after_repeated_wrong_pins(client, pin_user):
    url = reverse("accounts:login")
    for _ in range(5):
        r = client.post(url, {"username": pin_user.username, "password": "0000"})
        assert r.status_code == 200
    # Eşik aşıldı: doğru PIN bile beklerken kabul edilmez ve mesaj bekleme süresini söyler.
    r = client.post(url, {"username": pin_user.username, "password": TEST_PIN})
    assert r.status_code == 429
    assert "Çok fazla hatalı deneme" in r.content.decode()
    assert "_auth_user_id" not in client.session


def test_throttle_does_not_block_other_users_on_other_computers(client, pin_user, db):
    from django.test import Client as HttpClient

    url = reverse("accounts:login")
    for _ in range(5):
        client.post(url, {"username": pin_user.username, "password": "0000"})
    other = User.objects.create_user(username="diger", role=User.Role.LAWYER, password=TEST_PIN)
    assert client.post(url, {"username": other.username, "password": TEST_PIN}).status_code == 302
    # Aynı kullanıcı başka bir bilgisayardan (IP) hâlâ girebilir.
    remote = HttpClient(REMOTE_ADDR="10.0.0.9")
    assert (
        remote.post(url, {"username": pin_user.username, "password": TEST_PIN}).status_code == 302
    )


def test_throttle_wait_grows_and_expires(client, pin_user):
    from apps.accounts import throttle

    ip = "127.0.0.1"
    for _ in range(throttle.USER_IP_LIMIT):
        throttle.register_failure(pin_user.username, ip)
    first = throttle.remaining_wait(pin_user.username, ip)
    throttle.register_failure(pin_user.username, ip)
    assert throttle.remaining_wait(pin_user.username, ip) > first
    assert throttle.remaining_wait(pin_user.username, "10.9.9.9") == 0


def test_successful_login_resets_counter(client, pin_user):
    url = reverse("accounts:login")
    for _ in range(3):
        client.post(url, {"username": pin_user.username, "password": "0000"})
    assert (
        client.post(url, {"username": pin_user.username, "password": TEST_PIN}).status_code == 302
    )
    client.post(reverse("accounts:logout"))
    for _ in range(4):
        r = client.post(url, {"username": pin_user.username, "password": "0000"})
        assert r.status_code == 200


def test_failed_pin_is_written_to_activity_log(client, pin_user):
    from auditlog.models import LogEntry

    client.post(reverse("accounts:login"), {"username": pin_user.username, "password": "0000"})
    entry = LogEntry.objects.filter(actor=pin_user, action=LogEntry.Action.ACCESS).last()
    assert entry.changes == {"olay": "hatalı PIN"}
    assert "0000" not in str(entry.changes)


def test_wrong_pin_keeps_user_selected(client, pin_user):
    r = client.post(reverse("accounts:login"), {"username": pin_user.username, "password": "0000"})
    assert r.status_code == 200
    assert "PIN hatalı" in r.content.decode()
    assert r.context["form"]["username"].value() == pin_user.username


def test_pin_change_in_settings(client, pin_user):
    client.force_login(pin_user)
    url = reverse("accounts:settings")
    data = {"section": "pin", "old_pin": TEST_PIN}
    r = client.post(url, {**data, "new_pin": "12a4", "new_pin2": "12a4"})
    assert "new_pin" in r.context["forms"]["pin"].errors
    r = client.post(url, {**data, "new_pin": "1357", "new_pin2": "1357"})
    assert r.status_code == 302
    pin_user.refresh_from_db()
    assert pin_user.check_password("1357")
    # Eski PIN adresi ayarlara yönlenir.
    assert client.get(reverse("accounts:pin_change")).url == "/hesap/ayarlar/?bolum=pin"


def test_profile_settings(client, pin_user):
    client.force_login(pin_user)
    r = client.post(
        reverse("accounts:settings"),
        {
            "section": "profil",
            "first_name": "Yeni",
            "last_name": "AD",
            "email": "",
            "phone": "",
            "theme": "dark",
        },
    )
    assert r.status_code == 302
    pin_user.refresh_from_db()
    assert (pin_user.first_name, pin_user.theme) == ("Yeni", "dark")


def test_about_section_shows_version_and_hides_tech_from_non_admin(client, pin_user):
    from apps.core.version import app_version

    client.force_login(pin_user)  # avukat rolü
    url = reverse("accounts:settings")
    r = client.get(url, {"bolum": "hakkinda"})
    html = r.content.decode()
    assert r.context["active"] == "hakkinda"
    assert app_version() in html and "Hukuk Bürosu Otomasyonu" in html
    assert "Django" not in html

    pin_user.role = User.Role.ADMIN
    pin_user.save()
    html = client.get(url, {"bolum": "hakkinda"}).content.decode()
    assert "Django" in html and "Python" in html


def test_office_and_calendar_settings_admin_only(client, pin_user):
    from apps.office.models import OfficeSettings

    client.force_login(pin_user)  # avukat rolü
    url = reverse("accounts:settings")
    assert "ofis" not in client.get(url).context["forms"]
    r = client.post(url, {"section": "takvim", "calendar_ics_url": "https://x.test/a.ics"})
    assert r.status_code == 403

    pin_user.role = User.Role.ADMIN
    pin_user.save()
    secret = "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics"
    client.post(url, {"section": "takvim", "calendar_ics_url": secret})
    assert OfficeSettings.load().calendar_ics_url == secret
    # Boş gönderim mevcut adresi korur, adres sayfada görünmez.
    client.post(url, {"section": "takvim", "calendar_ics_url": ""})
    assert OfficeSettings.load().calendar_ics_url == secret
    assert secret not in client.get(url, {"bolum": "takvim"}).content.decode()
    client.post(url, {"section": "takvim", "calendar_ics_url": "", "clear": "on"})
    assert OfficeSettings.load().calendar_ics_url == ""


def test_google_calendar_api_settings_and_test_endpoint(client, pin_user, monkeypatch):
    pin_user.role = User.Role.ADMIN
    pin_user.save()
    client.force_login(pin_user)

    url = reverse("accounts:settings")

    # 1. API aktifken ID ve JSON zorunlu olmalı
    r = client.post(
        url,
        {
            "section": "takvim",
            "google_calendar_api_enabled": "on",
            "google_calendar_id": "",
            "google_service_account_json": "",
        },
    )
    assert r.status_code == 200
    assert "zorunludur" in r.content.decode()

    # 2. Geçerli JSON ve ID ile kaydetme
    valid_json = '{"type": "service_account", "project_id": "test-proj", "client_email": "test@test.iam.gserviceaccount.com"}'
    r = client.post(
        url,
        {
            "section": "takvim",
            "google_calendar_api_enabled": "on",
            "google_calendar_id": "test-cal@group.calendar.google.com",
            "google_service_account_json": valid_json,
        },
    )
    assert r.status_code == 302
    office = OfficeSettings.load()
    assert office.google_calendar_api_enabled is True
    assert office.google_calendar_id == "test-cal@group.calendar.google.com"
    assert "test-proj" in office.google_service_account_json

    # 3. Sayfa açıldığında ham JSON textarea'da gösterilmez, servis hesabı bilgisi görünür
    r_get = client.get(url, {"bolum": "takvim"})
    html = r_get.content.decode()
    assert "test@test.iam.gserviceaccount.com" in html
    assert valid_json not in html

    # 4. Boş gönderildiğinde mevcut JSON korunur
    client.post(
        url,
        {
            "section": "takvim",
            "google_calendar_api_enabled": "on",
            "google_calendar_id": "test-cal@group.calendar.google.com",
            "google_service_account_json": "",
        },
    )
    office = OfficeSettings.load()
    assert "test-proj" in office.google_service_account_json

    # 5. Test endpointi (GoogleApiTestView)
    from apps.agenda import google_sync

    monkeypatch.setattr(
        google_sync,
        "test_google_calendar_connection",
        lambda: (True, "Google Takvim bağlantısı başarılı!"),
    )
    r_test = client.post(reverse("agenda:google_test"))
    assert r_test.status_code == 200
    assert "Google Takvim bağlantısı başarılı!" in r_test.content.decode()

    # 6. clear_api_key ile anahtarı ve etkinliği temizleme
    client.post(
        url,
        {
            "section": "takvim",
            "clear_api_key": "on",
        },
    )
    office = OfficeSettings.load()
    assert office.google_service_account_json == ""
    assert office.google_calendar_api_enabled is False


def test_setup_office_users():
    call_command("setup_office_users", pin=TEST_PIN)
    assert User.objects.count() == 6
    admin = User.objects.get(username="yonetici.avukat")
    assert admin.is_office_admin and admin.is_superuser
    assert admin.check_password(TEST_PIN)
    assert admin.initials == "AY"
    assert list(User.objects.values_list("username", flat=True))[:3] == [
        "yonetici.avukat",
        "avukat.ayse",
        "avukat.mehmet",
    ]
    # Tekrar çalıştırmak mevcut PIN'i değiştirmez.
    admin.set_password("999999")
    admin.save()
    call_command("setup_office_users", pin=TEST_PIN)
    admin.refresh_from_db()
    assert admin.check_password("999999")


@pytest.mark.parametrize("pin", ["12", "12345", "12a4"])
def test_setup_rejects_invalid_pin(pin):
    # PIN tam 4 rakam olmalı (giriş ekranı 4. rakamda otomatik gönderir).
    with pytest.raises(CommandError):
        call_command("setup_office_users", pin=pin)


def test_expanded_user_roles_and_accountant_balance_default(client, pin_user):
    from apps.accounting.permissions import can_view_balances

    pin_user.role = User.Role.ADMIN
    pin_user.save()
    client.force_login(pin_user)
    url = reverse("accounts:settings")
    r = client.post(
        url,
        {
            "section": "kullanicilar",
            "first_name": "Selin",
            "last_name": "MUHASEBE",
            "role": User.Role.ACCOUNTANT,
            "title": "Mali İşler Sorumlusu",
            "pin": "2468",
            "order": "10",
            "is_active": "on",
        },
    )
    assert r.status_code == 302
    acc = User.objects.get(first_name="Selin")
    assert acc.role == User.Role.ACCOUNTANT
    assert can_view_balances(acc) is True  # muhasebe rolü varsayılan olarak bakiye görür


def test_use_assistant_assignee_toggle_controls_client_and_case_forms(client, pin_user):
    from apps.cases.forms import CaseForm
    from apps.clients.forms import ClientForm
    from apps.office.models import OfficeSettings

    office = OfficeSettings.load()
    assert office.use_assistant_assignee is True
    assert "responsible_intern" in ClientForm().fields
    assert ClientForm().fields["responsible_intern"].required is True
    assert "responsible_intern" in CaseForm().fields

    office.use_assistant_assignee = False
    office.save(update_fields=["use_assistant_assignee"])
    assert "responsible_intern" not in ClientForm().fields
    assert "responsible_intern" not in CaseForm().fields

    form = ClientForm(
        data={
            "kind": "person",
            "first_name": "Kemal",
            "last_name": "YILMAZ",
            "responsible_lawyer": pin_user.pk,
        }
    )
    assert form.is_valid(), form.errors
    c = form.save()
    assert c.responsible_intern is None


def test_case_visibility_mode_restricted_vs_public(db):
    from apps.cases.models import Case
    from apps.clients.models import Client
    from apps.core.permissions import filter_visible_cases, filter_visible_clients
    from apps.office.models import OfficeSettings

    admin = User.objects.create_user(username="adm", role=User.Role.ADMIN)
    senior = User.objects.create_user(username="sen", role=User.Role.SENIOR)
    secretary = User.objects.create_user(username="sec", role=User.Role.SECRETARY)
    lawyer1 = User.objects.create_user(username="law1", role=User.Role.LAWYER)
    lawyer2 = User.objects.create_user(username="law2", role=User.Role.LAWYER)
    intern1 = User.objects.create_user(username="int1", role=User.Role.INTERN)

    c1 = Client.objects.create(
        name="Müvekkil 1", responsible_lawyer=lawyer1, responsible_intern=intern1
    )
    c2 = Client.objects.create(name="Müvekkil 2", responsible_lawyer=lawyer2)
    case1 = Case.objects.create(
        client=c1,
        case_type="civil",
        subject="Alacak",
        responsible_lawyer=lawyer1,
        responsible_intern=intern1,
    )
    case2 = Case.objects.create(
        client=c2, case_type="civil", subject="Tahliye", responsible_lawyer=lawyer2
    )

    office = OfficeSettings.load()
    office.role_permissions = {
        "cases.view_all": [
            "admin",
            "senior",
            "lawyer",
            "intern",
            "paralegal",
            "secretary",
            "accountant",
        ]
    }
    office.save(update_fields=["role_permissions"])
    assert filter_visible_cases(Case.objects.all(), lawyer1).count() == 2

    office.role_permissions = {"cases.view_all": ["admin", "senior", "secretary", "accountant"]}
    office.save(update_fields=["role_permissions"])

    # Yönetici, kıdemli avukat ve büro geneli (sekreter) tümünü görür
    for u in (admin, senior, secretary):
        assert filter_visible_cases(Case.objects.all(), u).count() == 2
        assert filter_visible_clients(Client.objects.all(), u).count() == 2

    # Avukat ve stajyer yalnızca sorumlu olduklarını görür
    assert list(filter_visible_cases(Case.objects.all(), lawyer1)) == [case1]
    assert list(filter_visible_cases(Case.objects.all(), intern1)) == [case1]
    assert list(filter_visible_cases(Case.objects.all(), lawyer2)) == [case2]
    assert list(filter_visible_clients(Client.objects.all(), lawyer1)) == [c1]
    assert list(filter_visible_clients(Client.objects.all(), lawyer2)) == [c2]

    # Matriste avukat rolüne "tüm dosyaları görme" verilirse tüm avukatlar tümünü görür
    office.set_role_permission("cases.view_all", ["senior", "lawyer", "secretary", "accountant"])
    assert filter_visible_cases(Case.objects.all(), lawyer1).count() == 2
    assert filter_visible_cases(Case.objects.all(), intern1).count() == 1


def test_task_review_modes_optional_and_assistants_only(db):
    import datetime as dt

    from apps.cases.models import Case
    from apps.clients.models import Client
    from apps.office.models import OfficeSettings, TaskType
    from apps.tasks import services
    from apps.tasks.forms import TaskForm
    from apps.tasks.models import TaskStatus

    lawyer = User.objects.create_user(username="av1", role=User.Role.LAWYER, first_name="Avukat")
    intern = User.objects.create_user(username="stj1", role=User.Role.INTERN, first_name="Stajyer")
    cl = Client.objects.create(name="Müvekkil", responsible_lawyer=lawyer)
    case = Case.objects.create(
        client=cl, case_type="civil", subject="Konu", responsible_lawyer=lawyer
    )
    tt = TaskType.objects.filter(is_active=True, requires_document=False).first()

    office = OfficeSettings.load()
    # Avukat ve kıdemli kontrolcüsüz kapatabilir; stajyer için kontrolcü zorunlu.
    office.set_role_permission("tasks.close_without_review", ["senior", "lawyer"])

    # Yardımcı personel için kontrolcü zorunlu
    f_intern = TaskForm(
        data={
            "task_type": tt.pk,
            "title": "Stajyer Görevi",
            "case": case.pk,
            "assignee": intern.pk,
            "reviewer": "",
            "due_date": dt.date.today().isoformat(),
            "requires_accounting": "no",
        }
    )
    assert not f_intern.is_valid()
    assert "reviewer" in f_intern.errors

    # Avukat için kontrolcü boş bırakılabilir ve görev doğrudan kapatılabilir
    f_lawyer = TaskForm(
        data={
            "task_type": tt.pk,
            "title": "Avukat Görevi",
            "case": case.pk,
            "assignee": lawyer.pk,
            "reviewer": "",
            "due_date": dt.date.today().isoformat(),
            "requires_accounting": "no",
        }
    )
    assert f_lawyer.is_valid(), f_lawyer.errors
    task = f_lawyer.save()
    assert task.reviewer is None
    keys = [a.key for a in services.available_actions(task, lawyer)]
    assert "close" in keys
    assert "submit" not in keys

    services.perform(task, "close", lawyer, comment="Doğrudan tamamlandı")
    task.refresh_from_db()
    assert task.status == TaskStatus.DONE


def test_accounting_edit_permission_by_role(db):
    from apps.accounting.permissions import can_edit
    from apps.office.models import OfficeSettings

    admin = User.objects.create_user(username="adm_acc", role=User.Role.ADMIN)
    acc = User.objects.create_user(username="muh_acc", role=User.Role.ACCOUNTANT)
    lawyer = User.objects.create_user(username="av_acc", role=User.Role.LAWYER)

    office = OfficeSettings.load()
    assert can_edit(lawyer) is True  # varsayılan: tüm roller

    office.set_role_permission("accounting.edit", ["accountant"])
    assert can_edit(admin) is True  # yönetici her zaman yetkili
    assert can_edit(acc) is True
    assert can_edit(lawyer) is False

    office.set_role_permission("accounting.edit", ["accountant", "lawyer"])
    assert can_edit(lawyer) is True


def test_initial_setup_wizard_when_no_active_users(client, db):
    from apps.office.models import OfficeSettings

    User.objects.all().delete()
    # Aktif kullanıcı yokken giriş ekranı İlk Kurulum sihirbazına yönlendirir
    r_login = client.get(reverse("accounts:login"))
    assert r_login.status_code == 302
    assert r_login.url == reverse("accounts:initial_setup")

    r_get = client.get(reverse("accounts:initial_setup"))
    assert r_get.status_code == 200
    assert "İlk Kurulum Sihirbazı" in r_get.content.decode()

    # Hatalı PIN eşleşmemesi
    r_bad = client.post(
        reverse("accounts:initial_setup"),
        {
            "office_name": "Kaya Hukuk Bürosu",
            "first_name": "Ahmet",
            "last_name": "Kaya",
            "title": "Kurucu Avukat",
            "pin": "1234",
            "pin2": "4321",
        },
    )
    assert r_bad.status_code == 200
    assert "pin2" in r_bad.context["form"].errors

    # Geçerli kurulum
    r_ok = client.post(
        reverse("accounts:initial_setup"),
        {
            "office_name": "Kaya Hukuk Bürosu",
            "phone": "0212 555 00 00",
            "address": "İstanbul",
            "use_assistant_assignee": "",  # False
            "first_name": "Ahmet",
            "last_name": "Kaya",
            "title": "Kurucu Avukat",
            "pin": "2580",
            "pin2": "2580",
        },
    )
    assert r_ok.status_code == 302
    assert r_ok.url == reverse("core:home")

    office = OfficeSettings.load()
    assert office.name == "Kaya Hukuk Bürosu"
    assert office.slug == "kaya"
    assert office.use_assistant_assignee is False

    admin = User.objects.get(username="ahmet.kaya")
    assert admin.role == User.Role.ADMIN
    assert admin.last_name == "KAYA"
    assert admin.is_superuser is True
    assert admin.check_password("2580")

    # Kullanıcı oluştuktan sonra İlk Kurulum sayfası tekrar açılmaz, girişe yönlendirir
    r_after = client.get(reverse("accounts:initial_setup"))
    assert r_after.status_code == 302
    assert r_after.url == reverse("accounts:login")


def test_task_type_crud_and_requires_accounting(client, admin_user):
    from apps.office.models import TaskType

    client.force_login(admin_user)
    # Yeni bir görev türü ekleme (gelir/gider zorunlu olarak)
    qs = list(TaskType.objects.all())
    data = {
        "section": "gorev_turleri",
        "tt-TOTAL_FORMS": len(qs) + 1,
        "tt-INITIAL_FORMS": len(qs),
    }
    for i, t in enumerate(qs):
        data.update(
            {
                f"tt-{i}-id": t.pk,
                f"tt-{i}-name": t.name,
                f"tt-{i}-order": t.order,
                f"tt-{i}-points": t.points,
            }
        )
        if t.is_active:
            data[f"tt-{i}-is_active"] = "on"
        if t.requires_document:
            data[f"tt-{i}-requires_document"] = "on"
        if t.requires_accounting:
            data[f"tt-{i}-requires_accounting"] = "on"
    data.update(
        {
            f"tt-{len(qs)}-name": "Haciz Talebi",
            f"tt-{len(qs)}-order": 15,
            f"tt-{len(qs)}-points": 3,
            f"tt-{len(qs)}-is_active": "on",
            f"tt-{len(qs)}-requires_accounting": "on",
        }
    )
    r = client.post(reverse("accounts:settings"), data)
    assert r.status_code == 302
    new_tt = TaskType.objects.get(name="Haciz Talebi")
    assert new_tt.requires_accounting is True

    # Silme işlemi: Yeni türü silelim
    qs2 = list(TaskType.objects.all())
    delete_idx = next(i for i, t in enumerate(qs2) if t.pk == new_tt.pk)
    del_data = {
        "section": "gorev_turleri",
        "tt-TOTAL_FORMS": len(qs2),
        "tt-INITIAL_FORMS": len(qs2),
    }
    for i, t in enumerate(qs2):
        del_data.update(
            {
                f"tt-{i}-id": t.pk,
                f"tt-{i}-name": t.name,
                f"tt-{i}-order": t.order,
                f"tt-{i}-points": t.points,
            }
        )
        if t.is_active:
            del_data[f"tt-{i}-is_active"] = "on"
        if i == delete_idx:
            del_data[f"tt-{i}-DELETE"] = "on"
    r_del = client.post(reverse("accounts:settings"), del_data)
    assert r_del.status_code == 302
    assert not TaskType.objects.filter(pk=new_tt.pk).exists()


def test_calendar_colors_settings(client, admin_user):
    from apps.office.models import OfficeSettings

    client.force_login(admin_user)
    data = {
        "section": "takvim",
        "google_color_hearing": "9",
        "google_color_discovery": "2",
        "google_color_meeting": "5",
        "google_color_mediation": "11",
        "google_color_other": "8",
    }
    r = client.post(reverse("accounts:settings"), data)
    assert r.status_code == 302
    office = OfficeSettings.load()
    assert office.google_color_hearing == "9"
    assert office.google_color_discovery == "2"
    assert office.google_color_meeting == "5"
    assert office.google_color_mediation == "11"
    assert office.google_color_other == "8"
