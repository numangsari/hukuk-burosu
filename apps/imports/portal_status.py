"""Üst çubuktaki UYAP/UETS bağlantı göstergesi için durum hesabı."""

from datetime import timedelta

from django.utils import timezone

from .models import PortalConnection
from .portal_ingest import check_import_access

# Eklenti dakikada bir durum bildirir; bu süredir sessiz kalan bağlantı pasif sayılır.
CONNECTED_WINDOW = timedelta(minutes=3)
# Tarama sonucu "oturum açık" anlamına gelenler. `eksik`: oturum açık, bazı kayıtlar alınamadı.
ACTIVE_STATES = {"basladi", "tamamlandi", "eksik"}
SOURCES = (("uyap", "UYAP"), ("uets", "UETS"))
STATE_TEXT = {
    "aktif": "Aktif",
    "pasif": "Pasif",
    "kismi": "Bazı avukatlar pasif",
    "yok": "Bağlı eklenti yok",
}


def connection_state(connection, source, now):
    seen = connection.last_seen
    if not seen or now - seen > CONNECTED_WINDOW:
        return "pasif"
    return "aktif" if getattr(connection, f"{source}_status") in ACTIVE_STATES else "pasif"


def _summary(states):
    if not states:
        return "yok"
    if all(state == "aktif" for state in states):
        return "aktif"
    if any(state == "aktif" for state in states):
        return "kismi"
    return "pasif"


def _can_pair(user, connections):
    from .portal_sync import can_pair

    return can_pair(user) and not any(c.owner_id == user.pk for c in connections)


def portal_indicator(user, now=None):
    """Kullanıcının göreceği durum özeti. Avukat ve yönetici kişi listesini de görür."""
    now = now or timezone.now()
    connections = list(
        PortalConnection.objects.filter(active=True, owner__is_active=True).select_related("owner")
    )
    try:
        check_import_access(user)
        show_names = True
    except RuntimeError:
        show_names = False
    sources = []
    for key, label in SOURCES:
        people = [
            {
                "name": c.owner.get_full_name() or c.owner.username,
                "state": connection_state(c, key, now),
                "last_success": getattr(c, f"{key}_success_at"),
            }
            for c in connections
        ]
        state = _summary([person["state"] for person in people])
        sources.append(
            {
                "key": key,
                "label": label,
                "state": state,
                "text": STATE_TEXT[state],
                "people": people if show_names else [],
            }
        )
    return {
        "sources": sources,
        "show_names": show_names,
        "can_pair": _can_pair(user, connections),
    }
