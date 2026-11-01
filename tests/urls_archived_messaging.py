"""Kullanım dışı mesaj kodunu yalnızca denemelerde açan adresler."""

from django.urls import include, path

from apps.clients.urls import urlpatterns as client_patterns
from config.urls import urlpatterns as main_patterns

urlpatterns = [
    path(
        "muvekkiller/",
        include(
            (
                [
                    path("mesajlar/", include("apps.clients.messaging.urls")),
                    *client_patterns,
                ],
                "clients",
            )
        ),
    ),
    *[p for p in main_patterns if str(p.pattern) != "muvekkiller/"],
]
