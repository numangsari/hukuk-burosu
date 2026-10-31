from django.urls import path

from . import views

app_name = "tasks"
urlpatterns = [
    path("", views.TaskListView.as_view(), name="list"),
    path("yeni/", views.TaskCreateView.as_view(), name="create"),
    path("dosya-secenekleri/", views.case_options, name="case_options"),
    path("<int:pk>/", views.TaskDetailView.as_view(), name="detail"),
    path("<int:pk>/duzenle/", views.TaskUpdateView.as_view(), name="update"),
    path("<int:pk>/islem/", views.TaskActionView.as_view(), name="action"),
    path("<int:pk>/yorum/", views.TaskCommentView.as_view(), name="comment"),
]
