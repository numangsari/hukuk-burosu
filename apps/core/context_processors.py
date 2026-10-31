def app_context(request):
    from apps.office.models import OfficeSettings

    ctx = {"office": OfficeSettings.load()}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.notifications.services import run_daily_reminders_once

        run_daily_reminders_once()
        ctx["unread_notifications"] = user.notifications.filter(is_read=False).count()
        from apps.accounting.permissions import can_edit, can_view

        ctx["can_view_accounting"] = can_view(user)
        ctx["can_edit_accounting"] = can_edit(user)
        if user.is_office_admin:
            from apps.backups.services import backup_stale

            ctx["backup_stale"] = backup_stale()
    return ctx
