def app_context(request):
    from apps.office.models import OfficeSettings

    ctx = {"office": OfficeSettings.load()}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.notifications.services import run_daily_reminders_once

        run_daily_reminders_once()
        ctx["unread_notifications"] = user.notifications.filter(is_read=False).count()
    return ctx
