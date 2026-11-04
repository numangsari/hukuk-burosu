from django.urls import path

from . import views

app_name = "agenda"
urlpatterns = [
    path("", views.AgendaView.as_view(), name="calendar"),
    path("google-test/", views.GoogleApiTestView.as_view(), name="google_test"),
]
