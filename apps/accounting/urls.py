from django.urls import path

from . import views

app_name = "accounting"
urlpatterns = [
    path("", views.EntryListView.as_view(), name="list"),
    path("yeni/", views.EntryCreateView.as_view(), name="create"),
    path("<int:pk>/iptal/", views.EntryCancelView.as_view(), name="cancel"),
]
