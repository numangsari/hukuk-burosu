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
