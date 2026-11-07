from django.urls import path

from . import views, views_office

app_name = "accounting"
urlpatterns = [
    path("", views.EntryListView.as_view(), name="list"),
    path("yeni/", views.EntryCreateView.as_view(), name="create"),
    path("ofis/", views_office.OfficeEntryListView.as_view(), name="office_list"),
    path("ofis/yeni/", views_office.OfficeEntryCreateView.as_view(), name="office_create"),
    path(
        "ofis/<int:pk>/iptal/", views_office.OfficeEntryCancelView.as_view(), name="office_cancel"
    ),
    path("<int:pk>/iptal/", views.EntryCancelView.as_view(), name="cancel"),
]
