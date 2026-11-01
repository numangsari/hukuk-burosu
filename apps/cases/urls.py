from django.urls import path

from . import views
from . import views_records as rec

app_name = "cases"
urlpatterns = [
    path("", views.CaseListView.as_view(), name="list"),
    path("yeni/", views.CaseCreateView.as_view(), name="create"),
    path("<int:pk>/", views.CaseDetailView.as_view(), name="detail"),
    path("<int:pk>/duzenle/", views.CaseUpdateView.as_view(), name="update"),
    path("<int:pk>/sil/", views.CaseDeleteView.as_view(), name="delete"),
    path("<int:pk>/asama/", views.CaseStageView.as_view(), name="stage"),
    path("<int:pk>/safahat/yeni/", views.StepFormView.as_view(), name="step_add"),
    path("<int:pk>/safahat/<int:step_pk>/duzenle/", views.StepFormView.as_view(), name="step_edit"),
    path("<int:pk>/safahat/<int:step_pk>/esas/", views.StepApplyView.as_view(), name="step_apply"),
    path("<int:pk>/safahat/<int:step_pk>/sil/", views.StepDeleteView.as_view(), name="step_delete"),
    path("<int:pk>/kapat/", views.CaseCloseView.as_view(), name="close"),
    path("<int:pk>/yeniden-ac/", views.CaseReopenView.as_view(), name="reopen"),
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
    path("<int:pk>/durusma/", rec.HearingAddView.as_view(), name="hearing_add"),
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
