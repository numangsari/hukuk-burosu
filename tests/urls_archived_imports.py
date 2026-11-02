"""Kullanım dışı veri aktarımı kodunu yalnızca denemelerde açan adresler."""

from django.urls import include, path

from config.urls import urlpatterns as main_patterns

urlpatterns = [path("aktar/", include("apps.imports.urls")), *main_patterns]
