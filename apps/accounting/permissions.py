"""Muhasebe yetkisi.

Herkes muhasebe kaydı görür. Kaydı ekleme/iptal etme ve bakiye/cari/finansal rapor görme
yetkileri Ayarlar > Yetkiler'deki rol matrisinden gelir.
"""

from django.core.exceptions import PermissionDenied

from apps.core.permission_registry import has_perm


def _active(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active)


def can_view(user) -> bool:
    """Muhasebe kayıtlarını görme (dosya muhasebe sekmesi, muhasebe listesi)."""
    return _active(user)


def can_edit(user) -> bool:
    """Muhasebe kaydı girme ve iptal etme (rol matrisindeki "accounting.edit")."""
    return _active(user) and has_perm(user, "accounting.edit")


def can_view_balances(user) -> bool:
    """Müvekkil bakiyesi, borçluluk, cari hesap ve finansal raporlar ("accounting.balances")."""
    return _active(user) and has_perm(user, "accounting.balances")


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
