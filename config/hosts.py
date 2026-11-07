"""Yönetici ekranından düzenlenebilen izinli ana makine (host) listesi.

Django `settings.ALLOWED_HOSTS` değerini her istekte yineleyerek (iterate) okur. Bu sınıf,
ortam değişkeninden gelen sabit listeye `OfficeSettings.allowed_hosts` alanındaki adresleri ve
her zaman `localhost` / `127.0.0.1` adreslerini ekler; böylece adres değişince servisi yeniden
başlatmaya gerek kalmaz ve yanlış girilen liste sunucu makinesinden düzeltilebilir.
"""

import time

ALWAYS_ALLOWED = ("localhost", "127.0.0.1", "[::1]")


def parse_hosts(text: str) -> list[str]:
    """Boşluk, virgül veya noktalı virgülle ayrılmış metni küçük harfli adres listesine çevirir."""
    cleaned = (text or "").replace(",", " ").replace(";", " ")
    return [part.lower() for part in cleaned.split() if part.strip()]


class DynamicAllowedHosts(list):
    """Sabit listeye veritabanındaki ek adresleri kısa süreli önbellekle ekleyen liste."""

    TTL_SECONDS = 15

    def __init__(self, base=()):
        super().__init__(base)
        self._extra_cache: list[str] = []
        self._loaded_at = 0.0

    @property
    def base(self) -> list[str]:
        """Yalnızca ortam değişkeninden gelen sabit adresler."""
        return list(list.__iter__(self))

    @property
    def allows_everything(self) -> bool:
        return "*" in self.base

    def reset(self) -> None:
        """Ayar kaydedilince önbelleği boşaltır; sonraki istek yeni listeyi okur."""
        self._loaded_at = 0.0

    def _extra(self) -> list[str]:
        now = time.monotonic()
        if self._loaded_at and now - self._loaded_at < self.TTL_SECONDS:
            return self._extra_cache
        try:
            from apps.office.models import OfficeSettings

            text = OfficeSettings.objects.values_list("allowed_hosts", flat=True).first()
            self._extra_cache = parse_hosts(text or "")
        except Exception:
            # Veritabanı hazır değil (migrate öncesi, kesinti): sabit liste ile devam edilir.
            return self._extra_cache
        self._loaded_at = now
        return self._extra_cache

    def _all(self) -> list[str]:
        merged = [*self.base, *ALWAYS_ALLOWED, *self._extra()]
        return list(dict.fromkeys(merged))

    def __iter__(self):
        return iter(self._all())

    def __len__(self):
        return len(self._all())

    def __bool__(self):
        return True

    def __contains__(self, item):
        return item in self._all()
