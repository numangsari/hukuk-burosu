"""Liste kapsamı: "Bana atanmış" / "Tümü" düğmesi (`kapsam=bana`)."""

from django.db.models import Q


def wants_mine(params) -> bool:
    return params.get("kapsam") == "bana"


def responsible_q(user) -> Q:
    """Dosya ve müvekkilde kullanıcının sorumlu veya yardımcı sorumlu olduğu kayıtlar."""
    return Q(responsible_lawyer=user) | Q(responsible_intern=user)
