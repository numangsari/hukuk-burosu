"""Rol bazlı yetki yardımcıları."""

from django.contrib.auth.mixins import UserPassesTestMixin


def is_admin(user) -> bool:
    return user.is_authenticated and (user.is_superuser or user.role == user.Role.ADMIN)


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return is_admin(self.request.user)
