from django.urls import path

from . import views
from .webhooks import webhook

app_name = "messaging"
urlpatterns = [
    path("", views.InboxView.as_view(), name="inbox"),
    path("ayarlar/", views.OfficeSettingsView.as_view(), name="settings"),
    path("bildirim/", webhook, name="webhook"),
    path("numara/<str:phone>/", views.UnknownConversationView.as_view(), name="unknown"),
    path("muvekkil/<int:pk>/", views.ClientMessagesView.as_view(), name="client"),
    path(
        "muvekkil/<int:pk>/tercihler/", views.ContactSettingsView.as_view(), name="contact_settings"
    ),
    path("muvekkil/<int:pk>/gonder/", views.SendView.as_view(), name="send"),
    path(
        "muvekkil/<int:pk>/mesaj/<int:message_pk>/tekrar/", views.RetryView.as_view(), name="retry"
    ),
    path("muvekkil/<int:pk>/randevu/", views.AppointmentSaveView.as_view(), name="appointment_add"),
    path(
        "muvekkil/<int:pk>/randevu/<int:item_pk>/",
        views.AppointmentSaveView.as_view(),
        name="appointment_edit",
    ),
    path(
        "muvekkil/<int:pk>/randevu/<int:item_pk>/iptal/",
        views.AppointmentCancelView.as_view(),
        name="appointment_cancel",
    ),
]
