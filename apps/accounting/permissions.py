"""Muhasebe yetkisi.

Herkes muhasebe kaydı görür ve girer. Müvekkil bakiyesi, borçlu süzgeci, cari hesap
ekstresi, muhasebe toplamları ve finansal raporlar yalnızca yöneticiye ve yöneticinin
Ayarlar > Bakiye görme yetkisi'nden seçtiği kişilere görünür (`User.can_view_balances`).
"""

from django.core.exceptions import PermissionDenied

from apps.core.permissions import is_admin


def _active(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active)


def can_view(user) -> bool:
    """Muhasebe kayıtlarını görme (dosya muhasebe sekmesi, muhasebe listesi)."""
    return _active(user)


def can_edit(user) -> bool:
    """Muhasebe kaydı girme ve iptal etme."""
    return _active(user)


def can_view_balances(user) -> bool:
    """Müvekkil bakiyesi, borçluluk, cari hesap ve finansal raporlar."""
    return _active(user) and (is_admin(user) or user.can_view_balances)


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
