from django.urls import include, path

from . import views

app_name = "clients"
urlpatterns = [
    path("", views.ClientListView.as_view(), name="list"),
    path("yeni/", views.ClientCreateView.as_view(), name="create"),
    path("cakisma/", views.conflict_check, name="conflict_check"),
    path("mesajlar/", include("apps.clients.messaging.urls")),
    path("<int:pk>/", views.ClientDetailView.as_view(), name="detail"),
    path("<int:pk>/duzenle/", views.ClientUpdateView.as_view(), name="update"),
    path("<int:pk>/sil/", views.ClientDeleteView.as_view(), name="delete"),
    path("<int:pk>/varsayilanlar/", views.client_defaults, name="defaults"),
    path("<int:pk>/<str:kind>/", views.SubrecordView.as_view(), name="sub_add"),
    path(
        "<int:pk>/<str:kind>/<int:item_pk>/sil/",
        views.SubrecordDeleteView.as_view(),
        name="sub_delete",
    ),
]
