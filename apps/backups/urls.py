from django.urls import path

from . import views

app_name = "backups"
urlpatterns = [
    path("simdi/", views.BackupNowView.as_view(), name="now"),
    path("indir/<int:pk>/", views.BackupDownloadView.as_view(), name="download"),
    path("disa-aktar/excel-zip/", views.ExportAllListsZipView.as_view(), name="export_lists_zip"),
    path("disa-aktar/db-dump/", views.ExportDatabaseDumpView.as_view(), name="export_db_dump"),
    path("tetikle/", views.TriggerMonitorTaskView.as_view(), name="trigger_task"),
]
