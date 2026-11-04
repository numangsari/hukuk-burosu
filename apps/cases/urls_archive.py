from django.urls import path

from . import views_archive as va

app_name = "archive"

urlpatterns = [
    path("", va.ArchiveListView.as_view(), name="list"),
    path("yeni/", va.ArchiveFolderCreateView.as_view(), name="create"),
    path("tur-yeni/", va.ArchiveCategoryCreateView.as_view(), name="category_create"),
    path("siradaki-klasor/", va.archive_next_number, name="next_number"),
    path("bos-yerler/", va.archive_available_slots, name="available_slots"),
    path("klasor-secenekleri/", va.archive_available_folders, name="available_folders"),
    path("klasor/<path:folder_name>/", va.ArchiveFolderDetailView.as_view(), name="folder_detail"),
    path("<int:pk>/yer-guncelle/", va.ArchiveLocationUpdateView.as_view(), name="update_location"),
    path("etiketler/", va.ArchiveLabelsView.as_view(), name="labels"),
    path("disa-aktar/", va.ArchiveExportView.as_view(), name="export"),
]
