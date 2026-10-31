from django.urls import path

from . import views

app_name = "notifications"
urlpatterns = [
    path("", views.NotificationListView.as_view(), name="list"),
    path("okundu/", views.NotificationReadAllView.as_view(), name="read_all"),
    path("<int:pk>/", views.NotificationOpenView.as_view(), name="open"),
]
