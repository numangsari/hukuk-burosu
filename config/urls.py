from django.contrib import admin
from django.urls import include, path, re_path

from apps.core.media import protected_media

urlpatterns = [
    path("yonetim/", admin.site.urls),
    path("hesap/", include("apps.accounts.urls")),
    path("muvekkiller/", include("apps.clients.urls")),
    path("dosyalar/", include("apps.cases.urls")),
    path("takvim/", include("apps.agenda.urls")),
    path("gorevler/", include("apps.tasks.urls")),
    path("muhasebe/", include("apps.accounting.urls")),
    path("ara/", include("apps.search.urls")),
    path("aktivite/", include("apps.activity.urls")),
    path("raporlar/", include("apps.reports.urls")),
    path("yedek/", include("apps.backups.urls")),
    path("aktar/", include("apps.imports.urls")),
    path("", include("apps.core.urls")),
    # Yüklenen belgeler kayıt bazında yetki kontrolüyle sunulur (apps/core/media.py).
    re_path(r"^media/(?P<path>.*)$", protected_media),
]
