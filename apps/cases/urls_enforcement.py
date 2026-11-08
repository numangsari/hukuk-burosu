from django.urls import path

from . import views_enforcement as ve

app_name = "enforcement"

urlpatterns = [
    path("", ve.EnforcementListView.as_view(), name="list"),
]
