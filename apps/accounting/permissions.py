"""Muhasebe yetkisi.

Herkes muhasebe kaydı görür. Muhasebe kaydı ekleme/iptal etme yetkisi ofis ayarına göre
herkese açık veya yalnızca yönetici, muhasebe ve seçilen kişilere açık olabilir.
Müvekkil bakiyesi, borçlu süzgeci, cari hesap ekstresi, muhasebe toplamları ve finansal
raporlar yalnızca yöneticiye, muhasebe rolüne ve yöneticinin seçtiği kişilere görünür.
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
    if not _active(user):
        return False
    if (
        is_admin(user)
        or getattr(user, "role", None) == "accountant"
        or getattr(user, "can_manage_accounting", False)
    ):
        return True
    from apps.office.models import OfficeSettings

    office = OfficeSettings.load()
    return office.accounting_edit_mode == OfficeSettings.AccountingEditMode.EVERYONE


def can_view_balances(user) -> bool:
    """Müvekkil bakiyesi, borçluluk, cari hesap ve finansal raporlar."""
    return _active(user) and (
        is_admin(user) or user.can_view_balances or getattr(user, "role", None) == "accountant"
    )


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
