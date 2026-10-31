"""Muhasebe yetkisi: rol bazında Ofis Ayarları'ndan yönetilir, yönetici her zaman yetkilidir."""

from django.core.exceptions import PermissionDenied

from apps.core.permissions import is_admin
from apps.office.models import OfficeSettings


def _flag(user, action: str) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    if is_admin(user):
        return True
    office = OfficeSettings.load()
    return bool(getattr(office, f"{user.role}_can_{action}_accounting", False))


def can_view(user) -> bool:
    return _flag(user, "view")


def can_edit(user) -> bool:
    return can_view(user) and _flag(user, "edit")


class ViewRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not can_view(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class EditRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not can_edit(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
