"""PIN ile girişte deneme sınırı (kaba kuvvetle PIN bulmayı yavaşlatır).

Sayaçlar Django önbelleğinde tutulur; eşik aşıldıktan sonra her yeni hatalı denemede bekleme
süresi ikiye katlanır. Başarılı giriş kullanıcı+IP sayacını sıfırlar. Önbellek sunucu işlemine
bağlıdır: servis yeniden başlarsa sayaçlar sıfırlanır (kalıcı kilit değil, yavaşlatmadır).
"""

import hashlib
import time

from django.core.cache import cache

# (kapsam, eşik): eşikten sonraki her hatalı deneme beklemeyi uzatır.
USER_IP_LIMIT = 5  # aynı kullanıcı, aynı bilgisayar
IP_LIMIT = 20  # aynı bilgisayar, tüm kullanıcılar
USER_LIMIT = 40  # aynı kullanıcı, tüm bilgisayarlar (dağıtık deneme)
BASE_WAIT = 30  # saniye
MAX_WAIT = 15 * 60
WINDOW = 60 * 60  # sayaçlar bu süre sessiz kalırsa unutulur


def _key(scope: str, value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:24]
    return f"pin-throttle:{scope}:{digest}"


def _scopes(username: str, ip: str):
    username = (username or "").strip().lower()[:150]
    return (
        (_key("user-ip", f"{username}|{ip}"), USER_IP_LIMIT),
        (_key("ip", ip), IP_LIMIT),
        (_key("user", username), USER_LIMIT),
    )


def client_ip(request) -> str:
    # LAN'da ters vekil yok; REMOTE_ADDR dışındaki başlıklara güvenilmez (taklit edilebilir).
    return request.META.get("REMOTE_ADDR") or "-"


def _wait_for(count: int, limit: int) -> int:
    if count < limit:
        return 0
    return min(MAX_WAIT, BASE_WAIT * 2 ** (count - limit))


def remaining_wait(username: str, ip: str) -> int:
    """Kullanıcının yeni deneme yapabilmesi için beklemesi gereken saniye (0 = serbest)."""
    now = time.time()
    waits = []
    for key, limit in _scopes(username, ip):
        state = cache.get(key)
        if state:
            count, last = state
            wait = _wait_for(count, limit)
            if wait and (left := wait - (now - last)) > 0:
                waits.append(int(left) + 1)
    return max(waits, default=0)


def register_failure(username: str, ip: str) -> None:
    now = time.time()
    for key, _limit in _scopes(username, ip):
        count = (cache.get(key) or (0, now))[0] + 1
        cache.set(key, (count, now), WINDOW)


def register_success(username: str, ip: str) -> None:
    cache.delete(_key("user-ip", f"{(username or '').strip().lower()[:150]}|{ip}"))
