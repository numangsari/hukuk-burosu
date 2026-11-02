from django.urls import path

from . import poa_views, views

app_name = "imports"
urlpatterns = [
    path("", views.ImportView.as_view(), name="import"),
    path("sablon/", views.TemplateDownloadView.as_view(), name="template"),
    path("vekalet-listesi/", poa_views.PowerOfAttorneyReviewListView.as_view(), name="poa_review"),
    path(
        "vekalet-listesi/<int:row_number>/",
        poa_views.PowerOfAttorneyReviewDetailView.as_view(),
        name="poa_review_detail",
    ),
]
