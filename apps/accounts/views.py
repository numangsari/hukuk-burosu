from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.db.models import Q, Sum
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.core.permissions import is_admin
from apps.office.forms import (
    BackupSettingsForm,
    CalendarForm,
    DocumentsRootForm,
    OfficeForm,
    PortalLawyerAccessForm,
    TaskTypeFormSet,
)
from apps.office.models import OfficeSettings, TaskType

from .forms import BalanceViewersForm, PinChangeForm, PinLoginForm, ProfileForm, UserAdminForm
from .models import User


class PinLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = PinLoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["users"] = User.objects.filter(is_active=True)
        return ctx


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
            forms["yetkiler"] = BalanceViewersForm(*bound("yetkiler"))
            forms["klasor"] = DocumentsRootForm(*bound("klasor"), instance=office)
            edit = User.objects.filter(
                pk=request.GET.get("id") or request.POST.get("user_id") or 0
            ).first()
            forms["kullanicilar"] = UserAdminForm(
                *bound("kullanicilar"), instance=edit or User(), editor=user
            )
            forms["yedek"] = BackupSettingsForm(*bound("yedek"), instance=office)
            forms["gorev_turleri"] = TaskTypeFormSet(
                *bound("gorev_turleri"), queryset=TaskType.objects.all(), prefix="tt"
            )
        return forms

    def _render(self, request, forms, active):
        office = OfficeSettings.load()
        ctx = {
            "forms": forms,
            "active": active,
            "calendar_connected": bool(office.calendar_ics_url),
        }
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
        if active == "yedek":
            from apps.backups.models import BackupRecord
            from apps.backups.services import backup_ready

            ctx["backups"] = BackupRecord.objects.all()[:20]
            ctx["backup_problem"] = backup_ready()
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
        return render(request, self.template_name, ctx)

    def get(self, request):
        active = request.GET.get("bolum", "profil")
        forms = self._forms(request)
        if active not in forms and not (active == "puanlar" and is_admin(request.user)):
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
        saved = form.save()
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
