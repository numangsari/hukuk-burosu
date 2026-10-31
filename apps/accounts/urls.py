from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("giris/", views.PinLoginView.as_view(), name="login"),
    path("cikis/", auth_views.LogoutView.as_view(), name="logout"),
    path("pin/", views.PinChangeView.as_view(), name="pin_change"),
    path("tema/", views.ThemeToggleView.as_view(), name="theme_toggle"),
]
