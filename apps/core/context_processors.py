def app_context(request):
    from apps.office.models import OfficeSettings

    ctx = {"office": OfficeSettings.load()}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.accounting.permissions import can_edit, can_view, can_view_balances
        from apps.core.permission_registry import has_perm
        from apps.core.permissions import can_manage_routines

        ctx["can_view_accounting"] = can_view(user)
        ctx["can_edit_accounting"] = can_edit(user)
        ctx["can_view_balances"] = can_view_balances(user)
        ctx["can_manage_routines"] = can_manage_routines(user)
        ctx["can_create_hearing"] = has_perm(user, "hearings.create_manual")
        if user.is_office_admin:
            from apps.backups.services import backup_stale

            ctx["backup_stale"] = backup_stale()
    return ctx
