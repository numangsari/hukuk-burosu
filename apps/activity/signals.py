"""Giriş ve çıkış olaylarını aktivite kaydına (auditlog ACCESS) yazar."""

from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType


def _log(user, event, request):
    if user is None:
        return
    ip = (request.META.get("REMOTE_ADDR") or "") if request else ""
    LogEntry.objects.create(
        # type(user) değil: çıkışta kullanıcı tembel (lazy) sarmalayıcı olarak gelir
        content_type=ContentType.objects.get_for_model(user),
        object_pk=str(user.pk),
        object_id=user.pk,
        object_repr=str(user)[:200],
        action=LogEntry.Action.ACCESS,
        actor=user,
        remote_addr=ip or None,
        changes={"olay": event},
    )


def on_login(sender, request, user, **kwargs):
    _log(user, "giriş", request)


def on_logout(sender, request, user, **kwargs):
    _log(user, "çıkış", request)


def on_login_failed(sender, credentials, request=None, **kwargs):
    """Var olan bir kullanıcı için hatalı PIN denemesini kaydeder (PIN değeri yazılmaz)."""
    from apps.accounts.models import User

    username = (credentials or {}).get("username", "")
    user = User.objects.filter(username=username).first() if username else None
    _log(user, "hatalı PIN", request)
