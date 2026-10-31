from django.urls import path

from . import views

app_name = "backups"
urlpatterns = [path("simdi/", views.BackupNowView.as_view(), name="now")]
