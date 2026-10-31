"""Çıkar çatışması kontrolü: müvekkil ile karşı taraf kayıtlarını karşılaştırır."""

from django.db.models import Q

from apps.core.text import fold

from .models import Client, Party


def parties_matching(name: str, identity_no: str = "") -> list[Party]:
    """Müvekkille aynı kimlik no'ya veya aynı ada sahip karşı taraf kayıtları."""
    cond = Q()
    if identity_no:
        cond |= Q(identity_no=identity_no)
    key = fold(name)
    if key:
        cond |= Q(search_key=key)
    if not cond:
        return []
    return list(Party.objects.filter(cond).prefetch_related("case_links__case"))


def clients_matching(name: str, identity_no: str = "") -> list[Client]:
    """Karşı tarafla aynı kimlik no'ya veya aynı ada sahip müvekkil kayıtları."""
    cond = Q()
    if identity_no:
        cond |= Q(tckn=identity_no) | Q(vkn=identity_no)
    key = fold(name)
    if key:
        cond |= Q(search_key=key)
    if not cond:
        return []
    return list(Client.objects.filter(cond))
