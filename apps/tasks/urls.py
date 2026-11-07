from django.urls import path

from . import views, views_pool, views_routine

app_name = "tasks"
urlpatterns = [
    path("", views.TaskListView.as_view(), name="list"),
    path("yeni/", views.TaskCreateView.as_view(), name="create"),
    path("dosya-secenekleri/", views.case_options, name="case_options"),
    path("dilekce-havuzu/", views_pool.PetitionPoolListView.as_view(), name="pool"),
    path("dilekce-havuzu/yeni/", views_pool.PetitionSampleCreateView.as_view(), name="pool_create"),
    path(
        "dilekce-havuzu/<int:pk>/sil/",
        views_pool.PetitionSampleDeleteView.as_view(),
        name="pool_delete",
    ),
    path("rutin/", views_routine.RoutineListView.as_view(), name="routines"),
    path("rutin/yeni/", views_routine.RoutineCreateView.as_view(), name="routine_create"),
    path("rutin/<int:pk>/", views_routine.RoutineUpdateView.as_view(), name="routine_update"),
    path("rutin/<int:pk>/sil/", views_routine.RoutineDeleteView.as_view(), name="routine_delete"),
    path("<int:pk>/", views.TaskDetailView.as_view(), name="detail"),
    path("<int:pk>/duzenle/", views.TaskUpdateView.as_view(), name="update"),
    path("<int:pk>/islem/", views.TaskActionView.as_view(), name="action"),
    path("<int:pk>/not/", views.TaskNoteView.as_view(), name="note"),
    path("<int:pk>/yorum/", views.TaskCommentView.as_view(), name="comment"),
    path("<int:pk>/sil/", views.TaskDeleteView.as_view(), name="delete"),
    path(
        "<int:pk>/sablon/", views.PetitionTemplateDownloadView.as_view(), name="petition_template"
    ),
    path("<int:pk>/belge/", views.TaskDocumentUploadView.as_view(), name="doc_upload"),
    path(
        "<int:pk>/belge/<int:doc_pk>/sil/",
        views.TaskDocumentDeleteView.as_view(),
        name="doc_delete",
    ),
]
