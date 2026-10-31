from django.contrib.auth import views as auth_views
from django.urls import path

app_name = "accounts"
urlpatterns = [
    path(
        "giris/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("cikis/", auth_views.LogoutView.as_view(), name="logout"),
]
