"""Görevde sorumlu ve kontrolcü olarak seçilebilecek kullanıcılar."""

from django.db.models import Q

from apps.accounts.models import User


def assignee_choices(keep_pks=()):
    """Sorumlu yönetici olamaz; mevcut kayıttaki kişi (`keep_pks`) seçili kalabilir."""
    people = User.objects.filter(is_active=True).exclude(
        Q(role=User.Role.ADMIN) | Q(is_superuser=True)
    )
    if keep_pks:
        people = people | User.objects.filter(pk__in=[pk for pk in keep_pks if pk])
    return people.distinct()


def reviewer_choices(keep_pks=()):
    """Kontrolcü yalnızca yönetici, kıdemli avukat veya avukat olur; stajyer ve katip olamaz."""
    people = User.objects.filter(
        is_active=True, role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER]
    )
    if keep_pks:
        people = people | User.objects.filter(pk__in=[pk for pk in keep_pks if pk])
    return people.distinct()
