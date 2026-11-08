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


def can_edit(user, obj=None) -> bool:
    """Muhasebe kaydı girme ve iptal etme (rol matrisindeki "accounting.edit").

    `obj` (dosya, müvekkil veya hareket) verilirse sorumlu/yardımcı sorumlu ilişkisi de sayılır.
    """
    return _active(user) and has_perm(user, "accounting.edit", obj)


def can_exclude_portal(user, obj=None) -> bool:
    """UYAP kaynaklı hareketi hesap dışı bırakma ("accounting.exclude_portal")."""
    return _active(user) and has_perm(user, "accounting.exclude_portal", obj)


def can_view_balances(user, obj=None) -> bool:
    """Müvekkil bakiyesi, borçluluk, cari hesap ve finansal raporlar ("accounting.balances")."""
    return _active(user) and has_perm(user, "accounting.balances", obj)


class ViewRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not can_view(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class EditRequiredMixin:
    def permission_object(self, request):
        """Yetkinin sorumlu/yardımcı sorumlu ilişkisiyle denetleneceği kayıt (yoksa None)."""
        return None

    def dispatch(self, request, *args, **kwargs):
        if not can_edit(request.user):
            # Rolü yetkisizse yalnızca ilgili dosya/müvekkilin sorumlusu/yardımcısı geçebilir.
            obj = self.permission_object(request) if request.user.is_authenticated else None
            if obj is None or not can_edit(request.user, obj):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
