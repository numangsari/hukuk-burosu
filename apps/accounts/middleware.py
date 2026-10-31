"""Oturum güvenliği: ilk girişte PIN değiştirme zorunluluğu ve boşta kalan oturumun kapanması."""

import time

from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

# PIN değiştirme zorunluyken de açılabilen adresler
PIN_FREE_PREFIXES = (
    "/hesap/ayarlar/",
    "/hesap/cikis/",
    "/hesap/giris/",
    "/static/",
    "/media/office/",
)


def _redirect(request, url):
    if getattr(request, "htmx", False):
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = url
        return resp
    return redirect(url)


class IdleTimeoutMiddleware:
    """Ofis ayarındaki süre boyunca istek gelmeyen oturumu kapatır (0 = kapalı)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            from apps.office.models import OfficeSettings

            limit = OfficeSettings.load().idle_minutes * 60
            now = int(time.time())
            last = request.session.get("last_seen")
            if limit and last and now - last > limit:
                logout(request)
                return _redirect(request, f"{reverse('accounts:login')}?zaman_asimi=1")
            # Her istekte yazmamak için en çok dakikada bir güncellenir.
            if not last or now - last > 60:
                request.session["last_seen"] = now
        return self.get_response(request)


class ForcePinChangeMiddleware:
    """Varsayılan/yöneticinin verdiği PIN'le giren kullanıcıyı PIN değiştirmeye yönlendirir."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and user.must_change_pin
            and not request.path.startswith(PIN_FREE_PREFIXES)
        ):
            messages.warning(
                request,
                "Devam etmeden önce size verilen PIN'i kendi PIN'inizle değiştirin.",
            )
            return _redirect(request, f"{reverse('accounts:settings')}?bolum=pin")
        return self.get_response(request)
