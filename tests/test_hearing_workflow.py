import datetime as dt

import pytest
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import (
    Case,
    CaseEvent,
    CaseType,
    Hearing,
    HearingKind,
    HearingStatus,
)
from apps.tasks.models import Task

from .conftest import make_user

pytestmark = pytest.mark.django_db


def login(user):
    c = HttpClient()
    c.force_login(user)
    return c


@pytest.fixture
def case(admin_user, client_factory):
    return Case.objects.create(
        client=client_factory(name="TEST MÜVEKKİL"),
        case_type=CaseType.CIVIL,
        authority="İstanbul 1. Asliye Hukuk Mahkemesi",
        official_no="2026/100",
        subject="ALACAK DAVASI",
        archive_folder_no="Açık 1",
        archive_no="10",
        responsible_lawyer=admin_user,
        created_by=admin_user,
    )


def make_hearing(case, days, **kw):
    when = timezone.now() + dt.timedelta(days=days)
    defaults = {"case": case, "kind": HearingKind.HEARING, "starts_at": when}
    defaults.update(kw)
    return Hearing.objects.create(**defaults)


def form_data(case, lawyer, days=3, **kw):
    starts = (timezone.localtime() + dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    data = {
        "kind": HearingKind.HEARING,
        "case": case.pk,
        "assigned_to": lawyer.pk,
        "starts_at": starts,
        "attendance": "attend",
    }
    data.update(kw)
    return data


# ---- gün kuralı ----------------------------------------------------------------------


def test_hearing_is_done_once_its_time_has_come(case):
    now = timezone.now()
    assert not make_hearing(case, 0, starts_at=now + dt.timedelta(hours=1)).is_done
    assert make_hearing(case, 0, starts_at=now - dt.timedelta(minutes=1)).is_done
    assert make_hearing(case, -3).is_done
    assert not make_hearing(case, 1).is_done


def test_later_today_hearing_is_not_flagged_missing(admin_user, case):
    make_hearing(case, 0, starts_at=timezone.now() + dt.timedelta(hours=2), assigned_to=admin_user)
    r = login(admin_user).get(reverse("agenda:calendar"), {"view": "list"})
    assert r.context["attention_counts"]["upcoming"] == 0


def test_attendance_maps_to_flags(case):
    h = make_hearing(case, 3)
    assert h.attendance == "attend" and h.attendance_label == "Katılınacak"
    h.is_remote = True
    assert h.attendance_label == "E-duruşma"
    h.excuse_submitted = True
    assert h.attendance_label == "Mazeret"  # mazeret e-duruşmadan önceliklidir


# ---- oluşturma / düzenleme -------------------------------------------------------------


def test_create_requires_selecting_lawyer_not_defaulting_from_case(admin_user, case, lawyer):
    c = login(admin_user)
    data = form_data(case, lawyer)
    data.pop("assigned_to")
    r = c.post(reverse("hearings:create"), data)
    assert r.status_code == 200 and "assigned_to" in r.context["form"].errors
    assert not Hearing.objects.exists()  # dosyanın sorumlu avukatı otomatik atanmaz
    r = c.post(reverse("hearings:create"), form_data(case, lawyer, attendance="remote"))
    assert r.status_code == 302
    h = Hearing.objects.get()
    assert h.assigned_to == lawyer and h.is_remote and not h.excuse_submitted
    assert h.created_by == admin_user


def test_assignee_choices_include_intern_but_not_clerks(admin_user, intern, lawyer):
    clerk = make_user("katip2", "paralegal")
    form = login(admin_user).get(reverse("hearings:create")).context["form"]
    people = set(form.fields["assigned_to"].queryset)
    assert {admin_user, lawyer, intern} <= people and clerk not in people


def test_create_in_window_refreshes_parent(admin_user, case, lawyer):
    r = login(admin_user).post(
        reverse("hearings:create") + "?pencere=1", form_data(case, lawyer, attendance="excuse")
    )
    assert r.status_code == 200 and b"window.parent.location.reload()" in r.content
    assert Hearing.objects.get().excuse_submitted


def test_future_hearing_edits_in_place_and_past_cannot(admin_user, case, lawyer, intern):
    future = make_hearing(case, 4, assigned_to=lawyer)
    past = make_hearing(case, -1)
    c = login(admin_user)
    edit = reverse("hearings:edit", args=[future.pk])
    fragment = c.get(edit, HTTP_HX_REQUEST="true")
    assert fragment.status_code == 200 and b"<html" not in fragment.content
    r = c.post(
        edit + "?pencere=1",
        form_data(case, intern, days=6, attendance="excuse"),
        HTTP_HX_REQUEST="true",
    )
    assert r.status_code == 204 and r["HX-Redirect"].endswith(f"/{future.pk}/?pencere=1")
    future.refresh_from_db()
    assert future.assigned_to == intern and future.excuse_submitted
    assert c.get(reverse("hearings:edit", args=[past.pk])).status_code == 403


def test_detail_shows_edit_for_future_and_actions_for_done(admin_user, case):
    future = make_hearing(case, 4)
    done = make_hearing(case, 0)
    c = login(admin_user)
    page = c.get(reverse("hearings:detail", args=[future.pk])).content.decode()
    assert reverse("hearings:edit", args=[future.pk]) in page
    assert "Duruşma sonucu" not in page
    page = c.get(reverse("hearings:detail", args=[done.pk])).content.decode()
    assert reverse("hearings:edit", args=[done.pk]) not in page
    assert "1. Duruşma sonucu" in page and "2. Müvekkil bilgilendirme" in page
    assert "3. Görev" in page and "Görev oluştur" in page


# ---- sonuç ve bilgilendirme --------------------------------------------------------------


def test_result_requires_decision_and_saves_event_and_next_hearing(admin_user, case):
    h = make_hearing(case, -1, assigned_to=admin_user)
    c = login(admin_user)
    url = reverse("hearings:result", args=[h.pk])
    r = c.post(url, {"result": "   "})
    assert r.status_code == 200 and "result" in r.context["result_form"].errors
    next_at = (timezone.localtime() + dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
    r = c.post(url, {"result": "Ara karar: keşif yapılsın.", "next_hearing_at": next_at})
    assert r.status_code == 204
    h.refresh_from_db()
    assert h.result == "Ara karar: keşif yapılsın." and h.status == HearingStatus.HELD
    event = CaseEvent.objects.get(case=case, kind=CaseEvent.Kind.HEARING)
    assert "keşif" in event.description
    nxt = Hearing.objects.exclude(pk=h.pk).get()
    assert nxt.case == case and nxt.assigned_to == admin_user
    # Aynı sonucu yeniden kaydetmek zaman çizelgesini ve sonraki duruşmayı çoğaltmaz.
    c.post(url, {"result": "Ara karar: keşif yapılsın.", "next_hearing_at": next_at})
    assert CaseEvent.objects.filter(case=case, kind=CaseEvent.Kind.HEARING).count() == 1
    assert Hearing.objects.count() == 2


def test_result_not_allowed_for_future_hearing(admin_user, case):
    h = make_hearing(case, 3)
    r = login(admin_user).post(reverse("hearings:result", args=[h.pk]), {"result": "x"})
    assert r.status_code == 403


def test_next_hearing_date_is_optional(admin_user, case):
    h = make_hearing(case, -2)
    r = login(admin_user).post(reverse("hearings:result", args=[h.pk]), {"result": "Karar çıktı."})
    assert r.status_code == 204
    assert Hearing.objects.count() == 1


def test_inform_needs_result_then_marks_whatsapp_and_other(admin_user, case):
    h = make_hearing(case, -1)
    c = login(admin_user)
    url = reverse("hearings:inform", args=[h.pk])
    assert c.post(url, {"method": "whatsapp"}).status_code == 400  # önce sonuç
    h.result = "Karar: ret."
    h.save()
    assert c.post(url, {"method": "nope"}).status_code == 400
    assert c.post(url, {"method": "whatsapp"}).status_code == 204
    h.refresh_from_db()
    assert h.client_informed and h.client_informed_by == admin_user
    assert h.inform_method == "whatsapp" and h.client_informed_at
    r = c.post(url, {"method": "other"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 204 and "HX-Redirect" in r
    h.refresh_from_db()
    assert h.inform_method == "other"


def test_whatsapp_message_uses_result_and_next_date(admin_user, case):
    h = make_hearing(case, -1, result="Duruşma ertelendi.")
    nxt = make_hearing(case, 20)
    page = login(admin_user).get(reverse("hearings:detail", args=[h.pk])).content.decode()
    assert "Duruşma ertelendi." in page and nxt.starts_at.strftime("%d.%m.%Y") in page
    assert "data-wa-templates" in page and "wa-send-btn" in page


def test_inform_blocked_for_future_hearing_and_clientless(admin_user, case):
    future = make_hearing(case, 2, result="x")
    c = login(admin_user)
    assert (
        c.post(reverse("hearings:inform", args=[future.pk]), {"method": "other"}).status_code == 403
    )
    clientless = Hearing.objects.create(
        kind=HearingKind.HEARING,
        title="Dosyasız duruşma",
        starts_at=timezone.now() - dt.timedelta(days=1),
        result="x",
    )
    assert (
        c.post(reverse("hearings:inform", args=[clientless.pk]), {"method": "other"}).status_code
        == 403
    )


# ---- uyarılar ve liste ---------------------------------------------------------------------


def test_warnings_for_missing_result_and_inform(case):
    h = make_hearing(case, -1)
    assert h.result_missing and h.inform_missing and h.needs_attention
    h.result = "Karar."
    assert not h.result_missing and h.inform_missing
    h.client_informed_at = timezone.now()
    assert not h.needs_attention
    meeting = make_hearing(case, -1, kind=HearingKind.CLIENT_MEETING)
    assert not meeting.needs_attention  # toplantı ve görüşmelerde sonuç aranmaz
    assert not make_hearing(case, 2).needs_attention
    cancelled = make_hearing(case, -1, status=HearingStatus.CANCELLED)
    assert not cancelled.needs_attention


def test_list_tabs_date_filters_and_columns(admin_user, case, lawyer):
    upcoming = make_hearing(case, 3, assigned_to=lawyer)
    today = make_hearing(
        case, 0, assigned_to=lawyer, result="Karar", client_informed_at=timezone.now()
    )
    pending = make_hearing(case, -2, assigned_to=lawyer)
    past_ok = make_hearing(case, -9, assigned_to=lawyer, result="Karar", client_informed=True)
    meeting = make_hearing(case, 2, kind=HearingKind.CLIENT_MEETING)  # takvimde kalır, listede yok
    expert = make_hearing(case, 2, kind=HearingKind.EXPERT)
    c = login(admin_user)

    def rows(scope, **extra):
        r = c.get(reverse("agenda:calendar"), {"view": "list", "scope": scope, **extra})
        return {h.pk for h in r.context["hearings"]}, r

    assert rows("upcoming")[0] == {upcoming.pk, today.pk}  # bugün dahil
    assert rows("past")[0] == {pending.pk, past_ok.pk}
    assert rows("all")[0] == {
        upcoming.pk,
        today.pk,
    }  # "Tümü" kalktı: bilinmeyen kapsam yaklaşanlara düşer
    assert meeting.pk not in rows("upcoming")[0] and expert.pk not in rows("upcoming")[0]
    day = timezone.localdate().isoformat()
    assert rows("upcoming", baslangic=day, bitis=day)[0] == {today.pk}
    html = rows("upcoming")[1].content.decode()
    for column in ("Tarih / Saat", "Mahkeme / Esas", "Müvekkil", "Sorumlu avukat"):
        assert column in html
    assert "Katılma durumu" in html and "Takvim / Duruşma" in html
    for label in ("Yaklaşanlar", "Geçmiş", "Bugün", "Bu hafta", "Gelecek hafta", "Bu ay"):
        assert label in html
    assert ">Tümü" not in html.split("Sorumlu")[0] and 'name="tur"' not in html
    past_only = rows("past")[1].content.decode()
    assert "Gelecek hafta" not in past_only  # hızlı tarih filtreleri yalnızca Yaklaşanlar'da
    assert "Sonuç Bekleyenler" not in html and 'name="baslangic"' in html and 'name="bitis"' in html
    past_html = rows("past")[1].content.decode()
    assert (
        "Eksik: sonuç, bilgilendirme" in past_html and "Müvekkil bilgilendirilmedi" not in past_html
    )


def test_list_filters_lawyer_kind_and_attendance(admin_user, case, lawyer, intern):
    a = make_hearing(case, 3, assigned_to=lawyer, is_remote=True)
    b = make_hearing(case, 4, assigned_to=intern, kind=HearingKind.DISCOVERY)
    c = login(admin_user)

    def ids(**params):
        r = c.get(reverse("agenda:calendar"), {"view": "list", "scope": "upcoming", **params})
        return {h.pk for h in r.context["hearings"]}

    assert ids(avukat=lawyer.pk) == {a.pk}
    assert ids(katilim="remote") == {a.pk}
    assert ids(katilim="attend") == {b.pk}


def test_old_list_url_redirects_to_calendar_list(admin_user):
    r = login(admin_user).get(reverse("hearings:list") + "?scope=past")
    assert r.status_code == 302 and "view=list" in r["Location"] and "scope=past" in r["Location"]


# ---- görev oluşturma -------------------------------------------------------------------------


def test_task_from_hearing_prefills_case_and_links_hearing(admin_user, case, lawyer, intern):
    h = make_hearing(case, -1)
    c = login(admin_user)
    url = reverse("tasks:create") + f"?dosya={case.pk}&durusma={h.pk}&pencere=1"
    form = c.get(url).context["form"]
    assert form.initial["case"] == case and form.initial["client"] == case.client_id
    assert form.initial["assignee"]  # dosya sorumlusundan gelir
    from apps.office.models import TaskType

    data = {
        "task_type": TaskType.objects.exclude(name__iexact="Duruşma").first().pk,
        "title": "Duruşma sonrası işlem",
        "case": case.pk,
        "assignee": intern.pk,
        "reviewer": lawyer.pk,
        "due_date": (timezone.localdate() + dt.timedelta(days=3)).isoformat(),
        "requires_accounting": "no",
    }
    r = c.post(url, data)
    assert r.status_code == 200 and b"window.parent.location.reload()" in r.content
    assert Task.objects.get().hearing == h
    # Başka dosyaya ait duruşma bağlanmaz.
    other_case = Case.objects.create(
        client=case.client,
        case_type=CaseType.CIVIL,
        subject="Başka",
        archive_no="11",
        responsible_lawyer=admin_user,
        created_by=admin_user,
    )
    data2 = {**data, "case": other_case.pk, "title": "Başka dosya görevi"}
    c.post(url, data2)
    assert Task.objects.get(title="BAŞKA DOSYA GÖREVİ").hearing is None


def test_no_automatic_hearing_tasks_on_home(admin_user, case):
    make_hearing(case, 1, assigned_to=admin_user)
    login(admin_user).get(reverse("core:home"))
    assert not Task.objects.exists()  # otomatik duruşma görevi üretimi kaldırıldı


# ---- yetki ---------------------------------------------------------------------------------


def test_everyone_who_sees_the_hearing_can_act_restricted_mode_hides_it(
    case, lawyer, intern, settings
):
    from apps.office.models import OfficeSettings

    h = make_hearing(case, -1)
    assert login(lawyer).get(reverse("hearings:detail", args=[h.pk])).status_code == 200
    assert (
        login(lawyer).post(reverse("hearings:result", args=[h.pk]), {"result": "x"}).status_code
        == 204
    )
    office = OfficeSettings.load()
    office.role_permissions = {"cases.view_all": ["admin", "senior", "secretary", "accountant"]}
    office.save()
    stranger = make_user("yabanci", "lawyer")
    other = login(stranger)
    assert other.get(reverse("hearings:detail", args=[h.pk])).status_code == 404
    for name in ("result", "inform"):
        r = other.post(reverse(f"hearings:{name}", args=[h.pk]), {"method": "other", "result": "x"})
        assert r.status_code == 404


# ---- liste: doğrudan düzenle, sekme uyarıları, UYAP kurulum tarihi ---------------------------


def test_list_edit_button_opens_edit_form_directly(admin_user, case, lawyer):
    future = make_hearing(case, 4, assigned_to=lawyer)
    done = make_hearing(case, -1, assigned_to=lawyer)
    c = login(admin_user)
    url = reverse("agenda:calendar")
    html = c.get(url, {"view": "list", "scope": "upcoming"}).content.decode()
    assert f'href="{reverse("hearings:edit", args=[future.pk])}"' in html  # ara pencere yok
    past = c.get(url, {"view": "list", "scope": "past"}).content.decode()
    assert f'href="{reverse("hearings:detail", args=[done.pk])}"' in past  # yapılmışta işlemler
    r = c.post(
        reverse("hearings:edit", args=[future.pk]) + "?pencere=1",
        form_data(case, lawyer, days=9),
    )
    assert r.status_code == 200 and b"window.parent.location.reload()" in r.content


def test_tabs_show_missing_info_counts(admin_user, case):
    make_hearing(case, 0)  # bugün: sonuç ve bilgilendirme eksik
    make_hearing(case, -3)
    make_hearing(case, -4, result="Karar.", client_informed_at=timezone.now())
    make_hearing(case, 5)
    c = login(admin_user)
    r = c.get(reverse("agenda:calendar"), {"view": "list"})
    assert r.context["attention_counts"] == {
        "upcoming": 2,
        "past": 1,
    }  # bugün + sorumlusuz ilerideki
    html = r.content.decode()
    assert html.count('class="count count-warning"') == 2
    assert "Eksik: sorumlu avukat" in html
    assert "Eksik bilgisi olan duruşma" in html


def test_uyap_skips_hearings_before_installation_date(admin_user, case):
    from apps.imports.models import PortalCase
    from apps.imports.portal_case_sync import sync_record_hearings
    from apps.office.models import OfficeSettings

    office = OfficeSettings.load()
    office.installed_on = timezone.localdate()
    office.save(update_fields=["installed_on"])
    old = (timezone.localdate() - dt.timedelta(days=30)).strftime("%Y-%m-%d 10:00:00.0")
    new = (timezone.localdate() + dt.timedelta(days=10)).strftime("%Y-%m-%d 10:00:00.0")
    record = PortalCase.objects.create(
        fingerprint="kurulum-oncesi",
        authority="Mahkeme",
        number="2026/9",
        case=case,
        data={
            "durusmalar": [
                {"kayitId": 1, "tarihSaat": old, "islemTuruAciklama": "Duruşma"},
                {"kayitId": 2, "tarihSaat": new, "islemTuruAciklama": "Duruşma"},
            ]
        },
    )
    sync_record_hearings(case, record, default_user=admin_user)
    assert list(Hearing.objects.filter(case=case).values_list("portal_ref", flat=True)) == ["2"]


# ---- duruşma yalnızca UYAP'tan; etkinlikler elle ---------------------------------------------


def test_manual_hearing_kinds_need_permission_events_do_not(admin_user, lawyer, case):
    from apps.office.models import OfficeSettings

    c = login(lawyer)
    kinds = [
        value
        for value, _ in c.get(reverse("hearings:create")).context["form"].fields["kind"].choices
    ]
    assert "hearing" not in kinds and "discovery" not in kinds and "client_meeting" in kinds
    r = c.post(reverse("hearings:create"), form_data(case, lawyer))  # kind=hearing
    assert r.status_code == 200 and "kind" in r.context["form"].errors
    assert not Hearing.objects.exists()
    meeting = form_data(case, lawyer, kind=HearingKind.CLIENT_MEETING)
    assert c.post(reverse("hearings:create"), meeting).status_code == 302
    assert Hearing.objects.get().kind == HearingKind.CLIENT_MEETING
    # Yönetici varsayılan olarak elle duruşma ekler; yetki matristen verilebilir.
    assert (
        login(admin_user).post(reverse("hearings:create"), form_data(case, lawyer)).status_code
        == 302
    )
    OfficeSettings.load().set_role_permission("hearings.create_manual", ["lawyer"])
    assert (
        login(lawyer).post(reverse("hearings:create"), form_data(case, lawyer, days=5)).status_code
        == 302
    )


def test_uyap_hearing_core_fields_are_locked_in_edit_form(admin_user, case, lawyer):
    h = make_hearing(case, 6, assigned_to=lawyer, portal_ref="9001", authority="UYAP Mahkemesi")
    form = login(admin_user).get(reverse("hearings:edit", args=[h.pk])).context["form"]
    for name in ("kind", "case", "starts_at"):
        assert form.fields[name].disabled
    assert not form.fields["assigned_to"].disabled and not form.fields["attendance"].disabled
    other_day = form_data(case, lawyer, days=20, attendance="remote", authority="Değiştirilmiş")
    r = login(admin_user).post(reverse("hearings:edit", args=[h.pk]), other_day)
    assert r.status_code == 302
    h.refresh_from_db()
    assert h.is_remote and h.authority == "UYAP Mahkemesi"  # kilitli alan değişmez
    assert (timezone.localtime(h.starts_at).date() - timezone.localdate()).days == 6


def test_uyap_updates_time_and_cancels_hearing(admin_user, case):
    from apps.imports.models import PortalCase
    from apps.imports.portal_case_sync import sync_record_hearings
    from apps.office.models import OfficeSettings

    office = OfficeSettings.load()
    office.installed_on = timezone.localdate() - dt.timedelta(days=1)
    office.save(update_fields=["installed_on"])
    day1 = (timezone.localdate() + dt.timedelta(days=10)).strftime("%Y-%m-%d 10:00:00.0")
    day2 = (timezone.localdate() + dt.timedelta(days=12)).strftime("%Y-%m-%d 11:30:00.0")
    record = PortalCase.objects.create(
        fingerprint="uyap-guncel",
        authority="M",
        number="2026/7",
        case=case,
        data={"durusmalar": [{"kayitId": 5, "tarihSaat": day1, "islemTuruAciklama": "Duruşma"}]},
    )
    sync_record_hearings(case, record, default_user=admin_user)
    h = Hearing.objects.get(portal_ref="5")
    record.data = {
        "durusmalar": [{"kayitId": 5, "tarihSaat": day2, "islemTuruAciklama": "Duruşma"}]
    }
    sync_record_hearings(case, record, default_user=admin_user)
    h.refresh_from_db()
    assert timezone.localtime(h.starts_at).strftime("%H:%M") == "11:30"
    record.data = {
        "durusmalar": [
            {
                "kayitId": 5,
                "tarihSaat": day2,
                "islemTuruAciklama": "Duruşma",
                "islemSonucuAciklama": "İptal edildi",
            }
        ]
    }
    sync_record_hearings(case, record, default_user=admin_user)
    h.refresh_from_db()
    assert h.status == HearingStatus.CANCELLED


def test_manual_hearing_merges_with_later_uyap_record(admin_user, case):
    from apps.imports.models import PortalCase
    from apps.imports.portal_case_sync import sync_record_hearings
    from apps.office.models import OfficeSettings

    office = OfficeSettings.load()
    office.installed_on = timezone.localdate() - dt.timedelta(days=1)
    office.save(update_fields=["installed_on"])
    when = timezone.localtime() + dt.timedelta(days=9)
    manual = Hearing.objects.create(
        case=case, kind=HearingKind.HEARING, starts_at=when.replace(second=0, microsecond=0)
    )
    record = PortalCase.objects.create(
        fingerprint="uyap-birlesme",
        authority="M",
        number="2026/8",
        case=case,
        data={
            "durusmalar": [
                {
                    "kayitId": 77,
                    "tarihSaat": when.strftime("%Y-%m-%d %H:%M:00.0"),
                    "islemTuruAciklama": "Duruşma",
                }
            ]
        },
    )
    sync_record_hearings(case, record, default_user=admin_user)
    assert Hearing.objects.count() == 1  # mükerrer açılmaz
    manual.refresh_from_db()
    assert manual.portal_ref == "77"


def test_client_note_is_separate_and_in_whatsapp_preview(admin_user, case, lawyer):
    from apps.core.whatsapp import format_hearing_result_message

    h = make_hearing(case, -1, assigned_to=lawyer, result="Dosya karar için ertelendi.")
    c = login(admin_user)
    url = reverse("hearings:client_note", args=[h.pk])
    r = c.post(url, {"client_note": "Bir sonraki celsede hazır bulunmanız gerekmez."})
    assert r.status_code == 302
    h.refresh_from_db()
    assert h.client_note.startswith("Bir sonraki") and h.result == "Dosya karar için ertelendi."
    message = format_hearing_result_message(h)
    assert "Bir sonraki celsede hazır bulunmanız gerekmez." in message
    assert "Dosya karar için ertelendi." not in message and "Verilen Karar" not in message
    page = c.get(reverse("hearings:detail", args=[h.pk])).content.decode()
    assert "Müvekkile giden mesaj böyle görünecek" in page and "Bir sonraki celsede" in page
    # Yaklaşan duruşmada not girilemez.
    future = make_hearing(case, 4, assigned_to=lawyer)
    assert (
        c.post(reverse("hearings:client_note", args=[future.pk]), {"client_note": "x"}).status_code
        == 403
    )
