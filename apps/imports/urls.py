from django.urls import path

from . import office_views, poa_views, views

app_name = "imports"
urlpatterns = [
    path("", views.ImportView.as_view(), name="import"),
    path("sablon/", views.TemplateDownloadView.as_view(), name="template"),
    path("vekalet-listesi/", poa_views.PowerOfAttorneyReviewListView.as_view(), name="poa_review"),
    path(
        "dosya-listelerini-incele/",
        office_views.OfficeSourceListView.as_view(),
        name="office_review",
    ),
    path(
        "dosya-listelerini-incele/liste/",
        office_views.OfficeBulkView.as_view(),
        name="office_bulk",
    ),
    path(
        "dosya-listelerini-incele/<int:pk>/",
        office_views.OfficeSourceDetailView.as_view(),
        name="office_review_detail",
    ),
    path(
        "vekalet-listesi/<int:row_number>/",
        poa_views.PowerOfAttorneyReviewDetailView.as_view(),
        name="poa_review_detail",
    ),
]
