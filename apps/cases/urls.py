from django.urls import path

from . import views

app_name = "cases"
urlpatterns = [
    path("", views.CaseListView.as_view(), name="list"),
    path("yeni/", views.CaseCreateView.as_view(), name="create"),
    path("<int:pk>/", views.CaseDetailView.as_view(), name="detail"),
    path("<int:pk>/duzenle/", views.CaseUpdateView.as_view(), name="update"),
    path("<int:pk>/sil/", views.CaseDeleteView.as_view(), name="delete"),
    path("<int:pk>/taraf/", views.CasePartyAddView.as_view(), name="party_add"),
    path(
        "<int:pk>/taraf/<int:link_pk>/sil/",
        views.CasePartyRemoveView.as_view(),
        name="party_remove",
    ),
    path("<int:pk>/belge/", views.DocumentUploadView.as_view(), name="document_upload"),
    path(
        "<int:pk>/belge/<int:doc_pk>/sil/",
        views.DocumentDeleteView.as_view(),
        name="document_delete",
    ),
]
