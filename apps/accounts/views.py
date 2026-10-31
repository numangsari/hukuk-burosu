from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from apps.core.permissions import is_admin
from apps.office.forms import (
    AccountingPermissionsForm,
    BackupSettingsForm,
    CalendarForm,
    DocumentsRootForm,
    OfficeForm,
    TaskTypeFormSet,
)
from apps.office.models import OfficeSettings, TaskType

from .forms import PinChangeForm, PinLoginForm, ProfileForm, UserAdminForm
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
            forms["ofis"] = OfficeForm(*bound("ofis"), instance=office)
            forms["takvim"] = CalendarForm(*bound("takvim"), instance=office)
            forms["yetkiler"] = AccountingPermissionsForm(*bound("yetkiler"), instance=office)
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
        if active == "kullanicilar":
            ctx["users"] = User.objects.all()
        if active == "yedek":
            from apps.backups.models import BackupRecord
            from apps.backups.services import backup_ready

            ctx["backups"] = BackupRecord.objects.all()[:20]
            ctx["backup_problem"] = backup_ready()
        return render(request, self.template_name, ctx)

    def get(self, request):
        active = request.GET.get("bolum", "profil")
        forms = self._forms(request)
        if active not in forms:
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
