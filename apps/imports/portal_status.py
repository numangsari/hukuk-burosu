"""Üst çubuktaki UYAP/UETS bağlantı göstergesi için durum hesabı."""

from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User

from .models import PortalConnection, PortalLawyerAccess

# Eklenti dakikada bir durum bildirir; bu süredir sessiz kalan bağlantı pasif sayılır.
CONNECTED_WINDOW = timedelta(minutes=3)
# Oturum yoklaması bu süreden eskiyse güvenilmez; tarama sonucuna dönülür.
SESSION_FRESH = timedelta(minutes=10)
# Oturum açık olsa bile verinin akmasını engelleyen tarama durumları.
BLOCKED_STATES = {"izin_yok", "sunucu_yok"}
# Tarama sonucu "oturum açık" anlamına gelenler. `eksik`: oturum açık, bazı kayıtlar alınamadı.
ACTIVE_STATES = {"basladi", "tamamlandi", "eksik"}
SOURCES = (("uyap", "UYAP"), ("uets", "UETS"))
STATE_TEXT = {
    "aktif": "Aktarım var",
    "pasif": "Aktarım yok",
    "kismi": "Bazı avukatlarda aktarım yok",
    "yok": "Otomasyon izni verilmiş avukat yok",
}


def connection_state(connection, source, now):
    seen = connection.last_seen
    if not seen or now - seen > CONNECTED_WINDOW:
        return "pasif"
    status = getattr(connection, f"{source}_status")
    session_at = getattr(connection, f"{source}_session_at")
    session_ok = getattr(connection, f"{source}_session_ok")
    if session_at and session_ok is not None and now - session_at <= SESSION_FRESH:
        return "aktif" if session_ok and status not in BLOCKED_STATES else "pasif"
    return "aktif" if status in ACTIVE_STATES else "pasif"


REASON_TEXT = {
    "izin_yok": "Eklentiye izin verilmemiş; eşleştirmeyi ve avukat iznini kontrol edin",
    "sunucu_yok": "Eklenti sunucuya ulaşamadı veya sunucu hata verdi",
    "sekme_yok": "Sekme açık değil",
    "sekme_hazir_degil": "Sekme henüz yüklenmedi",
    "oturum_yok": "Oturum kapalı; yeniden giriş yapın",
    "durduruldu": "Aktarım durduruldu",
}


def inactive_reason(connection, source, now):
    """Bağlantı pasifse nedeni (kısa Türkçe metin); aktifse boş."""
    if connection_state(connection, source, now) == "aktif":
        return ""
    seen = connection.last_seen
    if not seen or now - seen > CONNECTED_WINDOW:
        return "Eklenti yanıt vermiyor (tarayıcı kapalı olabilir)"
    status = getattr(connection, f"{source}_status")
    if status in REASON_TEXT:
        return REASON_TEXT[status]
    session_at = getattr(connection, f"{source}_session_at")
    if (
        getattr(connection, f"{source}_session_ok") is False
        and session_at
        and now - session_at <= SESSION_FRESH
    ):
        return REASON_TEXT["oturum_yok"]
    return "Aktarım bilgisi yok"


def _summary(states):
    if not states:
        return "yok"
    if all(state == "aktif" for state in states):
        return "aktif"
    if any(state == "aktif" for state in states):
        return "kismi"
    return "pasif"


def _permitted_accounts(source):
    """Yöneticinin bu kaynak için otomasyon izni verdiği etkin avukatlar."""
    return list(
        PortalLawyerAccess.objects.select_related("user")
        .filter(
            user__is_active=True,
            user__role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER],
            **{f"{source}_enabled": True},
        )
        .order_by("user__first_name", "user__last_name", "pk")
    )


def portal_indicator(user, now=None):
    """Üst çubuk özeti. Her izinli avukat için o an aktarımı var mı (hesabı ana bilgisayarda
    açık, oturumu geçerli, eklenti bağlı) gösterilir; herkes görür."""
    now = now or timezone.now()
    connections = list(
        PortalConnection.objects.filter(active=True, owner__is_active=True).select_related("owner")
    )
    sources = []
    for key, label in SOURCES:
        people = []
        for access in _permitted_accounts(key):
            live = [
                c
                for c in connections
                if getattr(c, f"{key}_account_id") == access.pk
                and connection_state(c, key, now) == "aktif"
            ]
            matched = live or [
                c for c in connections if getattr(c, f"{key}_account_id") == access.pk
            ]
            people.append(
                {
                    "name": access.user.get_full_name() or access.user.username,
                    "state": "aktif" if live else "pasif",
                    "reason": ""
                    if live
                    else (
                        inactive_reason(matched[0], key, now)
                        if matched
                        else "Bu avukatın hesabı eklentiyle eşleşmemiş"
                    ),
                    "last_success": max(
                        (
                            getattr(c, f"{key}_success_at")
                            for c in matched
                            if getattr(c, f"{key}_success_at")
                        ),
                        default=None,
                    ),
                }
            )
        state = _summary([person["state"] for person in people])
        sources.append(
            {
                "key": key,
                "label": label,
                "state": state,
                "text": STATE_TEXT[state],
                "people": people,
            }
        )
    return {
        "sources": sources,
        "show_names": True,
        "can_pair": user.is_office_admin and not connections,
    }
