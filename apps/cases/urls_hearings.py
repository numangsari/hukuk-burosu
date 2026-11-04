from django.urls import path

from . import views_hearings as vh

app_name = "hearings"

urlpatterns = [
    path("", vh.HearingListView.as_view(), name="list"),
    path("yeni/", vh.HearingCreateStandaloneView.as_view(), name="create"),
    path("<int:pk>/duzenle/", vh.HearingEditView.as_view(), name="edit"),
    path("<int:pk>/sonuc/", vh.HearingResultModalView.as_view(), name="result"),
    path("<int:pk>/gorev-olustur/", vh.HearingTaskCreateView.as_view(), name="task_create"),
    path("<int:pk>/sil/", vh.HearingDeleteStandaloneView.as_view(), name="delete"),
    path("disa-aktar/", vh.HearingExportView.as_view(), name="export"),
]
