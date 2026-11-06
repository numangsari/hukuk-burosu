"""Rol bazlı yetki ve veri görünürlüğü yardımcıları."""

from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Exists, OuterRef, Q


def is_admin(user) -> bool:
    return bool(
        user and user.is_authenticated and (user.is_superuser or user.role == user.Role.ADMIN)
    )


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return is_admin(self.request.user)


def can_view_all_office_data(user) -> bool:
    """Kullanıcının tüm müvekkil ve dosyaları görüp göremeyeceğini döner.

    - Ayarlar > Yetkiler'de 'Herkese açık' (PUBLIC) seçiliyse tüm aktif kullanıcılar görür.
    - 'Sorumlu bazlı' (RESTRICTED) seçiliyse:
      Yönetici (admin), Kıdemli Avukat (senior), Sekreter (secretary), Muhasebe (accountant)
      ve özel yetki verilenler (`can_view_all_cases=True`) tümünü görür;
      Avukat (lawyer), Stajyer (intern) ve İcra Katibi (paralegal) yalnızca sorumlu/görevli
      olduğu kayıtları görür.
    """
    if not (user and user.is_authenticated and user.is_active):
        return False
    if is_admin(user) or getattr(user, "can_view_all_cases", False):
        return True
    if getattr(user, "role", None) in ("senior", "secretary", "accountant"):
        return True
    from apps.office.models import OfficeSettings

    office = OfficeSettings.load()
    return office.case_visibility_mode == OfficeSettings.CaseVisibilityMode.PUBLIC


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
        Q(assignee=user) | Q(reviewer=user)
    )
    return qs.filter(
        Q(responsible_lawyer=user)
        | Q(responsible_intern=user)
        | Q(client__responsible_lawyer=user)
        | Q(client__responsible_intern=user)
        | Exists(co_client_match)
        | Exists(task_match)
    )


def filter_visible_tasks(qs, user):
    """Görevleri süzer: sorumlu/kontrolcü olunan veya görünür dosyaya bağlı görevler."""
    if can_view_all_office_data(user):
        return qs
    from apps.cases.models import Case

    return qs.filter(
        Q(assignee=user)
        | Q(reviewer=user)
        | Q(case__in=filter_visible_cases(Case.objects.all(), user))
    )


def filter_visible_hearings(qs, user):
    """Duruşmaları süzer: görünür dosyaya bağlı olanlar ile dosyasız ofis etkinlikleri."""
    if can_view_all_office_data(user):
        return qs
    from apps.cases.models import Case

    return qs.filter(
        Q(case__in=filter_visible_cases(Case.objects.all(), user)) | Q(case__isnull=True)
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
        Q(assignee=user) | Q(reviewer=user)
    )
    return qs.filter(
        Q(responsible_lawyer=user)
        | Q(responsible_intern=user)
        | Exists(primary_case_match)
        | Exists(co_case_match)
        | Exists(task_match)
    )
