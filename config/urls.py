from django.contrib import admin
from django.urls import include, path, re_path

from apps.core.media import protected_media
from apps.imports import portal_sync, portal_views

urlpatterns = [
    path("tebligatlar/", portal_views.notice_list, name="notice_list"),
    path("tebligatlar/<int:pk>/gorev-yok/", portal_views.notice_no_task, name="notice_no_task"),
    path(
        "tebligatlar/<int:pk>/gorev-olustur/",
        portal_views.NoticeTaskCreateView.as_view(),
        name="notice_task_create",
    ),
    path("portal-inceleme/", portal_views.index, name="portal_review"),
    path("portal-inceleme/baglanti/", portal_sync.pair, name="portal_pair"),
    path("portal-inceleme/durum/", portal_sync.health, name="portal_health"),
    path(
        "portal-inceleme/izin/<int:pk>/sil/", portal_sync.remove_access, name="portal_remove_access"
    ),
    path("portal-inceleme/isim-kontrol/", portal_sync.check_name, name="portal_check_name"),
    path(
        "portal-inceleme/izin/<int:pk>/<str:source>/",
        portal_sync.toggle_access,
        name="portal_toggle_access",
    ),
    path(
        "portal-inceleme/baglanti/<int:pk>/durdur/",
        portal_sync.disconnect,
        name="portal_disconnect",
    ),
    path(
        "portal-inceleme/tebligat/<int:pk>/",
        portal_views.notice_detail,
        name="portal_notice_detail",
    ),
    path("portal-inceleme/eklentiden-al/", portal_sync.receive, name="portal_receive"),
    path(
        "portal-inceleme/tebligat-belgesi/<int:pk>/",
        portal_views.notice_document,
        name="portal_notice_document",
    ),
    path("portal-inceleme/<int:pk>/bagla/", portal_views.link_case, name="portal_case_link"),
    path("portal-inceleme/<int:pk>/", portal_views.detail, name="portal_review_detail"),
    path("yonetim/", admin.site.urls),
    path("hesap/", include("apps.accounts.urls")),
    path("muvekkiller/", include("apps.clients.urls")),
    path("dosyalar/", include("apps.cases.urls")),
    path("arsiv/", include("apps.cases.urls_archive")),
    path("durusmalar/", include("apps.cases.urls_hearings")),
    path("takvim/", include("apps.agenda.urls")),
    path("gorevler/", include("apps.tasks.urls")),
    path("muhasebe/", include("apps.accounting.urls")),
    path("ara/", include("apps.search.urls")),
    path("aktivite/", include("apps.activity.urls")),
    path("raporlar/", include("apps.reports.urls")),
    path("yedek/", include("apps.backups.urls")),
    path("veri-aktarim/", include("apps.imports.urls")),
    path("", include("apps.core.urls")),
    # Yüklenen belgeler kayıt bazında yetki kontrolüyle sunulur (apps/core/media.py).
    re_path(r"^media/(?P<path>.*)$", protected_media),
]
