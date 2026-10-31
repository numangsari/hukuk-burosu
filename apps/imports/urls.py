from django.urls import path

from . import views

app_name = "imports"
urlpatterns = [
    path("", views.ImportView.as_view(), name="import"),
    path("sablon/", views.TemplateDownloadView.as_view(), name="template"),
]
