"""Rol bazlı yetki ve veri görünürlüğü yardımcıları."""

from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Exists, OuterRef, Q

from .permission_registry import has_perm


def is_admin(user) -> bool:
    return bool(
        user and user.is_authenticated and (user.is_superuser or user.role == user.Role.ADMIN)
    )


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return is_admin(self.request.user)


def can_manage_routines(user) -> bool:
    """Rutin görev kurallarını yönetme (rol matrisindeki "tasks.routines" yetkisi)."""
    return has_perm(user, "tasks.routines")


class RoutineManagerMixin(UserPassesTestMixin):
    def test_func(self):
        return can_manage_routines(self.request.user)


class PermissionRequiredMixin(UserPassesTestMixin):
    """`required_permission` (rol matrisi anahtarı) olmayan kullanıcıya 403 verir."""

    required_permission = ""

    def test_func(self):
        return has_perm(self.request.user, self.required_permission)


def can_view_all_office_data(user) -> bool:
    """Kullanıcının tüm müvekkil ve dosyaları görüp göremeyeceğini döner.

    Rol matrisindeki "cases.view_all" yetkisi olmayan roller yalnızca sorumlu veya görevli
    olduğu dosya, müvekkil ve duruşmaları görür.
    """
    return has_perm(user, "cases.view_all")


def filter_visible_cases(qs, user):
    """Görünürlük ayarına göre kullanıcının erişebileceği dosyaları süzer."""
    if can_view_all_office_data(user):
        return qs
    from apps.cases.models import CaseCoClient
    from apps.tasks.models import Task

    co_client_match = CaseCoClient.objects.filter(case=OuterRef("pk")).filter(
        Q(client__responsible_lawyer=user) | Q(client__responsible_intern=user)
    )
    task_match = Task.objects.filter(case=OuterRef("pk")).filter(
        Q(assignee=user) | Q(reviewer=user) | Q(second_reviewer=user)
    )
    return qs.filter(
        Q(responsible_lawyer=user)
        | Q(responsible_intern=user)
        | Q(client__responsible_lawyer=user)
        | Q(client__responsible_intern=user)
        | Exists(co_client_match)
        | Exists(task_match)
    )


def filter_visible_clients(qs, user):
    """Görünürlük ayarına göre kullanıcının erişebileceği müvekkilleri süzer."""
    if can_view_all_office_data(user):
        return qs
    from apps.cases.models import Case, CaseCoClient
    from apps.tasks.models import Task

    primary_case_match = Case.objects.filter(client=OuterRef("pk")).filter(
        Q(responsible_lawyer=user) | Q(responsible_intern=user)
    )
    co_case_match = CaseCoClient.objects.filter(client=OuterRef("pk")).filter(
        Q(case__responsible_lawyer=user) | Q(case__responsible_intern=user)
    )
    task_match = Task.objects.filter(client=OuterRef("pk")).filter(
        Q(assignee=user) | Q(reviewer=user) | Q(second_reviewer=user)
    )
    return qs.filter(
        Q(responsible_lawyer=user)
        | Q(responsible_intern=user)
        | Exists(primary_case_match)
        | Exists(co_case_match)
        | Exists(task_match)
    )


def filter_visible_tasks(qs, user):
    """Kullanıcının görebileceği görevler: kendi görevleri veya görünür dosyaların görevleri.

    Dosyasız (ofis içi) görevi yalnızca sorumlusu, kontrolcüsü ve yönetici görür.
    """
    if is_admin(user):
        return qs
    if can_view_all_office_data(user):
        return qs.filter(
            Q(case__isnull=False) | Q(assignee=user) | Q(reviewer=user) | Q(second_reviewer=user)
        )
    from apps.cases.models import Case

    return qs.filter(
        Q(assignee=user)
        | Q(reviewer=user)
        | Q(second_reviewer=user)
        | Q(case__in=filter_visible_cases(Case.objects.all(), user))
    )


def filter_visible_hearings(qs, user):
    """Görünür dosyaların duruşmaları ile dosyasız (müvekkil randevusu/toplantı) kayıtlar."""
    if can_view_all_office_data(user):
        return qs
    from apps.cases.models import Case

    return qs.filter(
        Q(case__in=filter_visible_cases(Case.objects.all(), user)) | Q(case__isnull=True)
    )
