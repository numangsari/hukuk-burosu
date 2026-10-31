from django.apps import AppConfig


class ActivityConfig(AppConfig):
    name = "apps.activity"
    verbose_name = "Aktivite kaydı"

    def ready(self):
        from auditlog.registry import auditlog
        from django.contrib.auth import get_user_model
        from django.contrib.auth.signals import user_logged_in, user_logged_out

        from . import signals

        # Kullanıcı kayıtlarındaki değişiklikler (PIN/parola ve kişisel görünüm tercihleri hariç)
        auditlog.register(
            get_user_model(), exclude_fields=["password", "last_login", "theme", "page_size"]
        )
        user_logged_in.connect(signals.on_login, dispatch_uid="activity_login")
        user_logged_out.connect(signals.on_logout, dispatch_uid="activity_logout")
