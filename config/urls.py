from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("yonetim/", admin.site.urls),
    path("hesap/", include("apps.accounts.urls")),
    path("muvekkiller/", include("apps.clients.urls")),
    path("dosyalar/", include("apps.cases.urls")),
    path("takvim/", include("apps.agenda.urls")),
    path("gorevler/", include("apps.tasks.urls")),
    path("bildirimler/", include("apps.notifications.urls")),
    path("muhasebe/", include("apps.accounting.urls")),
    path("ara/", include("apps.search.urls")),
    path("aktivite/", include("apps.activity.urls")),
    path("raporlar/", include("apps.reports.urls")),
    path("yedek/", include("apps.backups.urls")),
    path("aktar/", include("apps.imports.urls")),
    path("", include("apps.core.urls")),
    # Yüklenen belgeler yalnızca giriş yapmış kullanıcıya sunulur
    # (LoginRequiredMiddleware tüm view'ları korur).
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
