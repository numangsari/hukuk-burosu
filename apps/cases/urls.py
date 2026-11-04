from django.urls import path

from . import views
from . import views_records as rec
from .views_seizures import SeizureDeleteView, SeizureSaveView

app_name = "cases"
urlpatterns = [
    path("", views.CaseListView.as_view(), name="list"),
    path("yeni/", views.CaseCreateView.as_view(), name="create"),
    path("<int:pk>/", views.CaseDetailView.as_view(), name="detail"),
    path("<int:pk>/duzenle/", views.CaseUpdateView.as_view(), name="update"),
    path("<int:pk>/sil/", views.CaseDeleteView.as_view(), name="delete"),
    path("<int:pk>/asama/", views.CaseStageView.as_view(), name="stage"),
    path("<int:pk>/kapat/", views.CaseCloseView.as_view(), name="close"),
    path("<int:pk>/yeniden-ac/", views.CaseReopenView.as_view(), name="reopen"),
    path("<int:pk>/taraf/", views.CasePartyAddView.as_view(), name="party_add"),
    path(
        "<int:pk>/taraf/<int:link_pk>/sil/",
        views.CasePartyRemoveView.as_view(),
        name="party_remove",
    ),
    path("<int:pk>/ilgili/yeni/", views.LinkAddView.as_view(), name="link_add"),
    path(
        "<int:pk>/ilgili/<int:member_pk>/ayir/", views.LinkDeleteView.as_view(), name="link_delete"
    ),
    path("<int:pk>/ilgili/<int:member_pk>/tasi/", views.LinkMoveView.as_view(), name="link_move"),
    path("<int:pk>/belge/", views.DocumentUploadView.as_view(), name="document_upload"),
    path(
        "<int:pk>/belge/<int:doc_pk>/sil/",
        views.DocumentDeleteView.as_view(),
        name="document_delete",
    ),
    path("<int:pk>/haciz/yeni/", SeizureSaveView.as_view(), name="seizure_add"),
    path("<int:pk>/haciz/<int:item_pk>/", SeizureSaveView.as_view(), name="seizure_edit"),
    path("<int:pk>/haciz/<int:item_pk>/sil/", SeizureDeleteView.as_view(), name="seizure_delete"),
    path("<int:pk>/durusma/yeni/", rec.HearingAddView.as_view(), name="hearing_add"),
    path(
        "<int:pk>/durusma/<int:item_pk>/sonuc/",
        rec.HearingResultView.as_view(),
        name="hearing_result",
    ),
    path(
        "<int:pk>/durusma/<int:item_pk>/sil/",
        rec.HearingDeleteView.as_view(),
        name="hearing_delete",
    ),
    path("<int:pk>/not/", rec.EventAddView.as_view(), name="event_add"),
    path("<int:pk>/not/<int:item_pk>/sil/", rec.EventDeleteView.as_view(), name="event_delete"),
]
