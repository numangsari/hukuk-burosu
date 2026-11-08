import contextlib

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import NON_FIELD_ERRORS
from django.db.models import ProtectedError, Q, Sum
from django.forms.utils import ErrorDict
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.permissions import is_admin
from apps.office.forms import (
    AllowedHostsForm,
    CalendarForm,
    DocumentsRootForm,
    OfficeForm,
    PortalLawyerAccessForm,
    TaskTypeFormSet,
)
from apps.office.models import HEARING_TASK_TYPE_NAME, OfficeSettings, TaskType

from . import throttle
from .forms import (
    InitialSetupForm,
    PinChangeForm,
    PinLoginForm,
    ProfileForm,
    RolePermissionsForm,
    UserAdminForm,
)
from .models import User


@method_decorator(login_not_required, name="dispatch")
class PinLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = PinLoginForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if not User.objects.exists():
            return redirect("accounts:initial_setup")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["users"] = User.objects.filter(is_active=True)
        return ctx

    def post(self, request, *args, **kwargs):
        username, ip = request.POST.get("username", ""), throttle.client_ip(request)
        wait = throttle.remaining_wait(username, ip)
        if wait:
            # PIN doğrulanmaz: beklerken doğru PIN bile denenmiş olmaz, sonuç sızmaz.
            form = self.get_form()
            minutes, seconds = divmod(wait, 60)
            duration = f"{minutes} dk {seconds} sn" if minutes else f"{seconds} sn"
            form._errors = ErrorDict()
            form._errors[NON_FIELD_ERRORS] = form.error_class(
                [f"Çok fazla hatalı deneme. {duration} sonra tekrar deneyin."],
                error_class="nonfield",
            )
            response = self.render_to_response(self.get_context_data(form=form))
            response.status_code = 429
            return response
        response = super().post(request, *args, **kwargs)
        if response.status_code == 302:  # başarılı giriş
            throttle.register_success(username, ip)
        else:
            throttle.register_failure(username, ip)
        return response


@method_decorator(login_not_required, name="dispatch")
class InitialSetupView(View):
    """Hiç kullanıcı olmadığında açılan ilk kurulum (onboarding) sihirbazı."""

    template_name = "accounts/initial_setup.html"

    def dispatch(self, request, *args, **kwargs):
        if User.objects.exists():
            return redirect("accounts:login")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return render(request, self.template_name, {"form": InitialSetupForm()})

    def post(self, request):
        form = InitialSetupForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        user = form.save()
        auth_login(request, user)
        messages.success(request, "Hukuk bürosu ilk kurulumu tamamlandı. Hoş geldiniz!")
        return redirect("core:home")


class SettingsView(View):
    """Kullanıcı ayarları (profil, görünüm, PIN) ve yöneticiye ofis/takvim ayarları."""

    template_name = "accounts/settings.html"
    ADMIN_SECTIONS = {
        "ofis",
        "takvim",
        "yetkiler",
        "klasor",
        "gorev_turleri",
        "kullanicilar",
        "yedek",
        "puanlar",
        "eklenti",
        "monitor",
        "kullanici_analizi",
        "veri_aktarim",
        "erisim",
    }

    def _forms(self, request, section=None, data=None, files=None):
        user, office = request.user, OfficeSettings.load()

        def bound(name):
            return (data, files) if section == name else (None, None)

        forms = {
            "profil": ProfileForm(*bound("profil"), instance=user),
            "pin": PinChangeForm(user, bound("pin")[0]),
        }
        if is_admin(user):
            from apps.imports.models import PortalLawyerAccess

            access = PortalLawyerAccess.objects.filter(
                pk=request.GET.get("izin") or request.POST.get("access_id") or 0
            ).first()
            forms["eklenti"] = PortalLawyerAccessForm(
                *bound("eklenti"), instance=access or PortalLawyerAccess()
            )
            forms["ofis"] = OfficeForm(*bound("ofis"), instance=office)
            forms["takvim"] = CalendarForm(*bound("takvim"), instance=office)
            forms["yetkiler"] = RolePermissionsForm(*bound("yetkiler"))
            forms["klasor"] = DocumentsRootForm(*bound("klasor"), instance=office)
            forms["erisim"] = AllowedHostsForm(*bound("erisim"), instance=office)
            edit = User.objects.filter(
                pk=request.GET.get("id") or request.POST.get("user_id") or 0
            ).first()
            forms["kullanicilar"] = UserAdminForm(
                *bound("kullanicilar"), instance=edit or User(), editor=user
            )
            forms["gorev_turleri"] = TaskTypeFormSet(
                *bound("gorev_turleri"),
                queryset=TaskType.objects.exclude(name__iexact=HEARING_TASK_TYPE_NAME),
                prefix="tt",
            )
        return forms

    def _render(self, request, forms, active):
        office = OfficeSettings.load()
        service_account_info = None
        if office.google_service_account_json:
            import json

            try:
                data = json.loads(office.google_service_account_json)
                service_account_info = {
                    "client_email": data.get("client_email", ""),
                    "project_id": data.get("project_id", ""),
                }
            except Exception:
                pass

        ctx = {
            "forms": forms,
            "active": active,
            "office": office,
            "calendar_connected": bool(office.calendar_ics_url),
            "service_account_info": service_account_info,
            "google_api_configured": bool(
                office.google_service_account_json and office.google_calendar_id
            ),
        }
        if active == "erisim" and is_admin(request.user):
            from django.conf import settings

            hosts = settings.ALLOWED_HOSTS
            ctx["fixed_hosts"] = getattr(hosts, "base", list(hosts))
            ctx["allows_everything"] = getattr(hosts, "allows_everything", "*" in hosts)
            ctx["current_host"] = request.get_host()
        if active == "eklenti" and is_admin(request.user):
            from datetime import timedelta

            from apps.imports.models import PortalConnection, PortalLawyerAccess

            connections = list(
                PortalConnection.objects.filter(active=True)
                .select_related("owner")
                .order_by("-created_at")
            )
            labels = {
                "bekliyor": "Bekliyor",
                "basladi": "Taranıyor",
                "tamamlandi": "Tamamlandı",
                "eksik": "Bazı bilgiler alınamadı",
                "oturum_yok": "Oturum gerekli",
                "sunucu_yok": "Sunucuya ulaşılamadı",
                "sekme_hazir_degil": "Sekme hazır değil",
                "sekme_yok": "Sekme açık değil",
                "durduruldu": "Durduruldu",
                "izin_yok": "İzinli kişi eşleşmedi",
            }
            for connection in connections:
                connection.recent = bool(
                    connection.last_seen
                    and timezone.now() - connection.last_seen <= timedelta(minutes=3)
                )
                connection.uyap_status_label = labels.get(connection.uyap_status, "Henüz bilgi yok")
                connection.uets_status_label = labels.get(connection.uets_status, "Henüz bilgi yok")
            ctx["portal_connections"] = connections
            ctx["portal_accesses"] = PortalLawyerAccess.objects.select_related("user").order_by(
                "user__first_name", "user__last_name"
            )
        if active == "kullanicilar":
            ctx["users"] = User.objects.all()
        if active == "klasor" and is_admin(request.user):
            from apps.backups.models import BackupRecord
            from apps.backups.services import backup_ready

            ctx["backups"] = BackupRecord.objects.all()[:20]
            ctx["backup_problem"] = backup_ready()
            from apps.core.office_lists import office_lists_status

            ctx["office_lists"] = office_lists_status()
        if active == "puanlar" and is_admin(request.user):
            import datetime as dt

            today = timezone.localdate()
            week_start = today - dt.timedelta(days=today.weekday())
            month_start = today.replace(day=1)
            ctx["point_users"] = User.objects.annotate(
                total_points=Sum("task_points__points"),
                week_points=Sum(
                    "task_points__points",
                    filter=Q(
                        task_points__earned_at__date__gte=week_start,
                        task_points__earned_at__date__lte=today,
                    ),
                ),
                month_points=Sum(
                    "task_points__points",
                    filter=Q(
                        task_points__earned_at__date__gte=month_start,
                        task_points__earned_at__date__lte=today,
                    ),
                ),
            ).order_by("first_name", "last_name")
        if active == "monitor" and is_admin(request.user):
            ctx.update(self._monitor_context(office))
        if active == "kullanici_analizi" and is_admin(request.user):
            ctx.update(self._user_analytics_context())
        if active == "veri_aktarim" and is_admin(request.user):
            from apps.backups.models import BackupRecord
            from apps.backups.services import backup_ready
            from apps.imports.models import ImportBatch

            ctx["backups"] = BackupRecord.objects.all()[:25]
            ctx["backup_problem"] = backup_ready()
            ctx["import_batches"] = ImportBatch.objects.select_related("created_by").order_by(
                "-created_at"
            )[:15]
        return render(request, self.template_name, ctx)

    def _monitor_context(self, office) -> dict:
        import datetime as dt
        from pathlib import Path

        from django.conf import settings
        from django.db import connection

        from apps.accounting.models import LedgerEntry
        from apps.backups.models import BackupRecord
        from apps.backups.services import backup_ready, last_success
        from apps.cases.models import Case, CaseStatus, Document, Seizure
        from apps.clients.models import Client, Party
        from apps.core.office_lists import office_lists_status
        from apps.imports.models import PortalCapture, PortalCase, PortalConnection, PortalNotice
        from apps.tasks.models import OPEN_STATUSES, Task, TaskStatus

        db_size = 0
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database())")
                row = cur.fetchone()
                db_size = row[0] if row else 0

        media_root = Path(settings.MEDIA_ROOT)
        media_size = 0
        media_files = 0
        if media_root.is_dir():
            for f in media_root.rglob("*"):
                if f.is_file():
                    media_files += 1
                    with contextlib.suppress(OSError):
                        media_size += f.stat().st_size

        today = timezone.localdate()
        connections = list(
            PortalConnection.objects.filter(active=True)
            .select_related("owner")
            .order_by("-created_at")
        )
        for c in connections:
            c.recent = bool(c.last_seen and timezone.now() - c.last_seen <= dt.timedelta(minutes=3))

        return {
            "db_size": db_size,
            "media_size": media_size,
            "media_files": media_files,
            "last_backup": last_success(),
            "recent_backups": BackupRecord.objects.all()[:5],
            "backup_problem": backup_ready(),
            "office_lists": office_lists_status(),
            "portal_connections": connections,
            "counts": {
                "clients": Client.objects.count(),
                "parties": Party.objects.count(),
                "cases_total": Case.objects.count(),
                "cases_open": Case.objects.exclude(status=CaseStatus.CLOSED).count(),
                "cases_closed": Case.objects.filter(status=CaseStatus.CLOSED).count(),
                "cases_missing_info": Case.objects.filter(
                    Q(client__isnull=True)
                    | Q(subject="")
                    | Q(archive_folder_no="")
                    | Q(archive_no="")
                ).count(),
                "tasks_open": Task.objects.filter(status__in=OPEN_STATUSES).count(),
                "tasks_review": Task.objects.filter(status=TaskStatus.REVIEW).count(),
                "tasks_overdue": Task.objects.filter(
                    status__in=OPEN_STATUSES, due_date__lt=today
                ).count(),
                "documents": Document.objects.count(),
                "ledger_active": LedgerEntry.objects.filter(is_cancelled=False).count(),
                "seizures_due": Seizure.objects.filter(
                    case__status=CaseStatus.OPEN,
                    renewal_on__isnull=False,
                    renewal_on__lte=today + dt.timedelta(days=14),
                ).count(),
                "portal_cases": PortalCase.objects.count(),
                "portal_notices": PortalNotice.objects.count(),
                "portal_notices_pending": PortalNotice.objects.filter(
                    resolved_at__isnull=True
                ).count(),
                "portal_captures": PortalCapture.objects.count(),
            },
        }

    def _user_analytics_context(self) -> dict:
        import datetime as dt

        from auditlog.models import LogEntry
        from django.db.models import Count, Max

        from apps.tasks.models import OPEN_STATUSES, Task, TaskStatus

        today = timezone.localdate()
        week_start = today - dt.timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        users = list(
            User.objects.annotate(
                total_points=Sum("task_points__points"),
                month_points=Sum(
                    "task_points__points",
                    filter=Q(
                        task_points__earned_at__date__gte=month_start,
                        task_points__earned_at__date__lte=today,
                    ),
                ),
            ).order_by("-is_active", "order", "first_name", "last_name")
        )

        # LogEntry counts per user
        log_stats = {
            row["actor_id"]: row
            for row in LogEntry.objects.filter(actor__isnull=False)
            .values("actor_id")
            .annotate(
                total_ops=Count("id"),
                today_ops=Count("id", filter=Q(timestamp__date=today)),
                week_ops=Count("id", filter=Q(timestamp__date__gte=week_start)),
                month_ops=Count("id", filter=Q(timestamp__date__gte=month_start)),
                creates=Count("id", filter=Q(action=LogEntry.Action.CREATE)),
                updates=Count("id", filter=Q(action=LogEntry.Action.UPDATE)),
                logins=Count("id", filter=Q(action=LogEntry.Action.ACCESS)),
                last_op=Max("timestamp"),
            )
        }

        # Task workload per user
        open_tasks_by_user = dict(
            Task.objects.filter(status__in=OPEN_STATUSES)
            .values_list("assignee_id")
            .annotate(c=Count("id"))
        )
        overdue_tasks_by_user = dict(
            Task.objects.filter(status__in=OPEN_STATUSES, due_date__lt=today)
            .values_list("assignee_id")
            .annotate(c=Count("id"))
        )
        review_waiting_by_user = dict(
            Task.objects.filter(status=TaskStatus.REVIEW)
            .values_list("reviewer_id")
            .annotate(c=Count("id"))
        )
        closed_tasks_by_user = dict(
            Task.objects.filter(status=TaskStatus.DONE)
            .values_list("assignee_id")
            .annotate(c=Count("id"))
        )

        for u in users:
            st = log_stats.get(u.pk, {})
            u.today_ops = st.get("today_ops", 0)
            u.week_ops = st.get("week_ops", 0)
            u.month_ops = st.get("month_ops", 0)
            u.total_ops = st.get("total_ops", 0)
            u.creates = st.get("creates", 0)
            u.updates = st.get("updates", 0)
            u.logins = st.get("logins", 0)
            u.last_activity_at = st.get("last_op") or u.last_login
            u.open_task_count = open_tasks_by_user.get(u.pk, 0)
            u.overdue_task_count = overdue_tasks_by_user.get(u.pk, 0)
            u.review_waiting_count = review_waiting_by_user.get(u.pk, 0)
            u.closed_task_count = closed_tasks_by_user.get(u.pk, 0)

        return {"analytics_users": users}

    def get(self, request):
        active = request.GET.get("bolum", "profil")
        if active == "yedek":
            return redirect(f"{reverse('accounts:settings')}?bolum=klasor")
        forms = self._forms(request)
        if active not in forms and not (
            active in {"puanlar", "monitor", "kullanici_analizi", "veri_aktarim"}
            and is_admin(request.user)
        ):
            active = "profil"
        return self._render(request, forms, active)

    def post(self, request):
        section = request.POST.get("section", "")
        if section in self.ADMIN_SECTIONS and not is_admin(request.user):
            return HttpResponseForbidden()
        forms = self._forms(request, section, request.POST, request.FILES)
        form = forms.get(section)
        if form is None:
            return redirect("accounts:settings")
        if not form.is_valid():
            return self._render(request, forms, section)
        try:
            saved = form.save()
        except ProtectedError:
            messages.error(
                request,
                "Silinmek istenen görev türüne ait sistemde kayıtlı görev(ler) bulunduğu için "
                "silinemedi. Bu türü silmek yerine pasife alabilirsiniz.",
            )
            return self._render(request, forms, section)
        if section == "kullanicilar":
            messages.success(request, f"{saved} kaydedildi.")
            return redirect(f"{reverse('accounts:settings')}?bolum=kullanicilar&id={saved.pk}")
        if section == "eklenti":
            messages.success(request, "Eklenti izni kaydedildi. Otomatik aktarım henüz kapalı.")
            return redirect(f"{reverse('accounts:settings')}?bolum=eklenti")
        if section == "pin":
            update_session_auth_hash(request, saved)
        if section == "takvim":
            cache.clear()  # yeni adresle takvim hemen yeniden çekilsin
        messages.success(request, "Ayarlar kaydedildi.")
        return redirect(f"{reverse('accounts:settings')}?bolum={section}")


class ThemeToggleView(View):
    """Açık/koyu tema tercihini kaydeder; sayfa tarafında tema anında değişir."""

    def post(self, request):
        user = request.user
        user.theme = User.Theme.LIGHT if user.theme == User.Theme.DARK else User.Theme.DARK
        user.save(update_fields=["theme"])
        return HttpResponse(status=204)


class PetitionTemplatesView(View):
    def get(self, request):
        if not is_admin(request.user):
            return HttpResponseForbidden()
        return render(
            request,
            "accounts/petition_templates.html",
            {"types": TaskType.objects.filter(is_active=True)},
        )

    def post(self, request):
        import uuid
        import zipfile
        from pathlib import Path

        from apps.core import folders
        from apps.core.uploads import MAX_UPLOAD

        if not is_admin(request.user):
            return HttpResponseForbidden()
        type_id = request.POST.get("task_type", "")
        task_type = TaskType.objects.filter(
            pk=type_id if type_id.isdigit() else 0, is_active=True
        ).first()
        upload = request.FILES.get("template")
        root = folders.root()
        error = None
        if not task_type or not upload:
            error = "Görev türünü ve şablonu seçin."
        elif not root or not root.is_dir():
            error = "Önce erişilebilir ofis klasörünü ayarlayın."
        elif Path(upload.name).suffix.lower() not in (".udf", ".docx") or upload.size > MAX_UPLOAD:
            error = "En fazla 50 MB büyüklüğünde UDF veya DOCX dosyası seçin."
        elif not zipfile.is_zipfile(upload):
            error = "Şablon dosyası okunamadı."
        else:
            with zipfile.ZipFile(upload) as archive:
                names = archive.namelist()
                needed = (
                    "content.xml" if upload.name.lower().endswith(".udf") else "word/document.xml"
                )
                if needed not in names or any(name.lower().endswith(".sgn") for name in names):
                    error = "İmzalanmamış ve geçerli bir şablon seçin."
        if error:
            messages.error(request, error)
            return redirect("accounts:petition_templates")
        directory = root / "Şablon Dilekçeler"
        if directory.is_symlink():
            messages.error(request, "Şablon klasörü güvenli değil.")
            return redirect("accounts:petition_templates")
        try:
            directory.mkdir(exist_ok=True)
            name = f"{task_type.pk}-{uuid.uuid4().hex}{Path(upload.name).suffix.lower()}"
            upload.seek(0)
            with (directory / name).open("xb") as destination:
                for chunk in upload.chunks():
                    destination.write(chunk)
        except OSError:
            messages.error(request, "Şablon ofis klasörüne kaydedilemedi.")
            return redirect("accounts:petition_templates")
        task_type.petition_template = name
        task_type.save(update_fields=["petition_template"])
        messages.success(request, "Şablon kaydedildi.")
        return redirect("accounts:petition_templates")
