"""Google Takvim API tek yönlü senkronizasyon servisi.

Güvenlik & Bütünlük Kuralları:
1. Veri akışı tek yönlüdür: Yalnızca sistemdeki duruşma ve etkinlikler
   Google Takvim'e aktarılır.
2. Google Takvim'deki mevcut veya harici hiçbir etkinliğe asla dokunulmaz.
3. Duruşma kaydındaki `google_event_id` ile güncelleme yapılır, mükerrer
   kayıt kesinlikle engellenir.
"""

import datetime as dt
import json
import logging
import threading

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone

from apps.cases.models import Hearing, HearingKind, HearingStatus
from apps.office.models import OfficeSettings

log = logging.getLogger(__name__)

# Arka plan eşitlemesine tanınan süre (sn); yeniden deneme daha yeni kayıtlara dokunmaz.
BACKGROUND_SYNC_GRACE_SECONDS = 120


def get_calendar_service(office: OfficeSettings | None = None, require_enabled: bool = True):
    """Google Calendar v3 API istemcisini döndürür; ayar yoksa None döner."""
    if office is None:
        office = OfficeSettings.load()

    if require_enabled and not office.google_calendar_api_enabled:
        return None, None

    cal_id = (office.google_calendar_id or "").strip()
    raw_json = (office.google_service_account_json or "").strip()
    if not cal_id or not raw_json:
        return None, None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(raw_json)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/calendar.events"],
        )
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return service, cal_id
    except Exception as e:
        log.warning("Google Calendar API servisi başlatılamadı: %s", e)
        return None, None


def hearing_to_google_payload(hearing: Hearing) -> dict:
    """Hearing modelini Google Calendar Event payload formatına çevirir."""
    office = OfficeSettings.load()

    # Önek: Keşif için [Keşif] (Duruşma ve Ön İnceleme için önek yok)
    prefix = ""
    if hearing.kind == HearingKind.DISCOVERY:
        prefix = "[Keşif] "
    elif hearing.kind == HearingKind.MEDIATION:
        prefix = "[Arabuluculuk] "
    elif hearing.kind == HearingKind.CLIENT_MEETING:
        prefix = "[Görüşme] "
    elif hearing.kind == HearingKind.CLIENT_MEETING_OFFSITE:
        prefix = "[Görüşme - ofis dışı] "
    elif hearing.kind == HearingKind.OFFICE_MEETING:
        prefix = "[Toplantı] "
    elif hearing.kind == HearingKind.EXPERT:
        prefix = "[Bilirkişi] "
    elif hearing.kind == HearingKind.OTHER:
        prefix = "[Diğer] "
    if hearing.is_remote:
        prefix = "[E-duruşma] " + prefix

    # Sorumlu adı veya Mazeret:
    # Kullanıcı kuralı: Soyadı yazılmasın (yalnızca adı), köşeli parantez olmasın,
    # mazeret gönderilecek seçildiyse Mazeret yazılsın.
    if hearing.excuse_submitted:
        responsible_str = "Mazeret"
    else:
        responsible = hearing.assigned_to
        if not responsible and hearing.case:
            responsible = hearing.case.responsible_lawyer
        if responsible:
            responsible_str = (responsible.first_name or responsible.username).strip()
        else:
            responsible_str = hearing.get_kind_display()

    case_part = ""
    if hearing.case:
        case_part = hearing.case.display_name
    elif hearing.authority:
        case_part = hearing.authority
    elif hearing.title:
        case_part = hearing.title
    else:
        case_part = hearing.get_kind_display()

    client = hearing.client or (hearing.case.client if hearing.case else None)
    client_part = f" ({client})" if client else ""

    summary = f"{prefix}{responsible_str} - {case_part}{client_part}".strip()

    lines = []
    if hearing.case:
        lines.append(f"Dosya: {hearing.case.display_name}")
        lines.append(f"Esas/No: {hearing.case.official_no or '—'}")
    if client:
        lines.append(f"Müvekkil: {client}")
    if hearing.assigned_to:
        lines.append(f"Duruşma Sorumlusu: {hearing.assigned_to}")
    elif hearing.case and hearing.case.responsible_lawyer:
        lines.append(f"Sorumlu Avukat: {hearing.case.responsible_lawyer}")

    authority = hearing.authority or (hearing.case.authority if hearing.case else "")
    if authority:
        lines.append(f"Mahkeme/Birim: {authority}")

    if hearing.excuse_submitted:
        lines.append("\n[SİSTEM BİLGİSİ: Bu duruşmaya mazeret sunulması kararlaştırılmıştır.]")

    if hearing.notes:
        lines.append(f"\nNotlar:\n{hearing.notes}")
    if hearing.result:
        lines.append(f"\nSonuç / Kararlar:\n{hearing.result}")
    if hearing.portal_ref:
        lines.append(f"\nUYAP Ref: {hearing.portal_ref}")

    lines.append(f"\n(Bu etkinlik {office.name} Otomasyonu tarafından oluşturulmuştur.)")
    description = "\n".join(lines)

    starts_at = timezone.localtime(hearing.starts_at)
    if hearing.ends_at:
        ends_at = timezone.localtime(hearing.ends_at)
    else:
        ends_at = starts_at + dt.timedelta(minutes=30)

    tz_str = "Europe/Istanbul"
    # Etkinlik türüne göre Google Takvim rengi:
    if hearing.kind in (HearingKind.HEARING, HearingKind.PRELIMINARY):
        color_id = getattr(office, "google_color_hearing", "9") or "9"
    elif hearing.kind == HearingKind.DISCOVERY:
        color_id = getattr(office, "google_color_discovery", "2") or "2"
    elif hearing.kind in (
        HearingKind.CLIENT_MEETING,
        HearingKind.CLIENT_MEETING_OFFSITE,
        HearingKind.OFFICE_MEETING,
    ):
        color_id = getattr(office, "google_color_meeting", "5") or "5"
    elif hearing.kind == HearingKind.MEDIATION:
        color_id = getattr(office, "google_color_mediation", "11") or "11"
    else:
        color_id = getattr(office, "google_color_other", "8") or "8"

    return {
        "summary": summary,
        "description": description,
        "colorId": color_id,
        "start": {
            "dateTime": starts_at.isoformat(),
            "timeZone": tz_str,
        },
        "end": {
            "dateTime": ends_at.isoformat(),
            "timeZone": tz_str,
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 24 * 60},  # 1 gün önce
                {"method": "popup", "minutes": 60},  # 1 saat önce
            ],
        },
    }


# Google'ın "etkinlik yok" yanıtları; yalnızca bunlarda yerel etkinlik kimliği bırakılır.
GONE_STATUSES = {404, 410}


def _http_status(error) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "resp", None), "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _set_sync_pending(hearing: Hearing, pending: bool) -> None:
    """Eşitleme bekleme işaretini audit kaydı üretmeden günceller."""
    if hearing.pk and hearing.google_sync_pending != pending:
        Hearing.objects.filter(pk=hearing.pk).update(google_sync_pending=pending)
    hearing.google_sync_pending = pending


def sync_hearing_to_google(hearing: Hearing) -> str | None:
    """Tek bir duruşmayı Google Takvim'e tek yönlü yazar veya günceller.

    API açıkken eşitleme başarısız olursa duruşma `google_sync_pending` ile işaretlenir;
    `retry_google_sync` komutu bu kayıtları sonra yeniden dener. Hata kullanıcıya
    yansıtılmaz, duruşma kaydı her durumda saklanır.
    """
    service, cal_id = get_calendar_service()
    if service is None or not cal_id:
        if OfficeSettings.load().google_calendar_api_enabled:
            _set_sync_pending(hearing, True)
        return None

    from googleapiclient.errors import HttpError

    # Eğer iptal edildiyse ve Google'da varsa kaldıralım
    if hearing.status == HearingStatus.CANCELLED:
        if hearing.google_event_id:
            try:
                service.events().delete(
                    calendarId=cal_id,
                    eventId=hearing.google_event_id,
                ).execute()
            except HttpError as e:
                if _http_status(e) not in GONE_STATUSES:
                    # Yetki/kota/sunucu hatası: etkinlik Google'da duruyor olabilir; kimlik
                    # korunur, sonra yeniden denenir.
                    log.warning("Google Takvim silme hatası (Hearing #%s): %s", hearing.pk, e)
                    _set_sync_pending(hearing, True)
                    return None
                log.info("Google takvim etkinliği zaten silinmiş: %s", hearing.google_event_id)
            except Exception as e:
                # Ağ hatası: etkinlik kimliği korunur, sonra yeniden denenir.
                log.warning("Google Takvim silme hatası (Hearing #%s): %s", hearing.pk, e)
                _set_sync_pending(hearing, True)
                return None
            hearing.google_event_id = ""
            hearing.save(update_fields=["google_event_id"])
        _set_sync_pending(hearing, False)
        return None

    payload = hearing_to_google_payload(hearing)

    try:
        if hearing.google_event_id:
            try:
                updated = (
                    service.events()
                    .patch(calendarId=cal_id, eventId=hearing.google_event_id, body=payload)
                    .execute()
                )
                _set_sync_pending(hearing, False)
                return updated.get("id")
            except HttpError as e:
                # 404 ise etkinlik Google tarafında silinmiş demektir, yeniden insert edeceğiz
                if getattr(e, "status_code", None) == 404 or getattr(e, "resp", {}).status == 404:
                    log.info(
                        "Google event bulunamadı, yeniden oluşturuluyor: %s",
                        hearing.google_event_id,
                    )
                else:
                    raise

        # Yeni etkinlik oluştur (mükerrerliği önlemek için ID'yi kaydediyoruz)
        created = service.events().insert(calendarId=cal_id, body=payload).execute()
        event_id = created.get("id", "")
        if event_id:
            hearing.google_event_id = event_id
            hearing.save(update_fields=["google_event_id"])
        _set_sync_pending(hearing, not event_id)
        return event_id
    except Exception as e:
        log.warning("Google Takvim senkronizasyon hatası (Hearing #%s): %s", hearing.pk, e)
        _set_sync_pending(hearing, True)
        return None


def _thread_main(job, args) -> None:
    try:
        job(*args)
    finally:
        connections.close_all()  # iş parçacığına ait veritabanı bağlantısını kapatır


def _spawn(job, *args) -> None:
    """İşi arka planda çalıştırır (Waitress/runserver sürecinde yardımcı iş parçacığı)."""
    threading.Thread(target=_thread_main, args=(job, args), daemon=True, name="google-sync").start()


def _run_queued_sync(hearing_pk: int) -> None:
    """Kuyruktaki eşitlemeyi güncel kayıtla çalıştırır."""
    try:
        hearing = Hearing.objects.filter(pk=hearing_pk).first()
        if hearing is not None:
            sync_hearing_to_google(hearing)
    except Exception:  # noqa: BLE001 - arka plan işi sessizce çökmemeli, yeniden deneme devralır
        log.exception("Google Takvim arka plan eşitlemesi başarısız (Hearing #%s)", hearing_pk)


def queue_hearing_google_sync(hearing: Hearing) -> None:
    """Duruşma eşitlemesini istekten ayırır: kayıt bekliyor işaretlenir, Google çağrısı arka planda.

    İşlem tamamlanınca (`on_commit`) iş parçacığı başlar. Süreç araya girip kapanırsa bekleyen
    işaret kalır ve `retry_google_sync` komutu devralır. `GOOGLE_SYNC_BACKGROUND` kapalıysa
    (testler) eşitleme çağrı içinde yapılır.
    """
    if not getattr(settings, "GOOGLE_SYNC_BACKGROUND", False):
        sync_hearing_to_google(hearing)
        return
    if not OfficeSettings.load().google_calendar_api_enabled:
        return
    _set_sync_pending(hearing, True)
    pk = hearing.pk
    transaction.on_commit(lambda: _spawn(_run_queued_sync, pk))


def delete_hearing_from_google(hearing: Hearing) -> None:
    """Yalnızca bu duruşmaya ait Google Takvim kaydını siler."""
    if not hearing.google_event_id:
        return
    service, cal_id = get_calendar_service()
    if service is None or not cal_id:
        return

    from googleapiclient.errors import HttpError

    try:
        service.events().delete(
            calendarId=cal_id,
            eventId=hearing.google_event_id,
        ).execute()
    except HttpError as e:
        log.info("Google takvim etkinliği silinirken hata: %s", e)
    except Exception as e:
        log.warning("Google Takvim silme hatası: %s", e)

    hearing.google_event_id = ""
    hearing.save(update_fields=["google_event_id"])


def sync_all_hearings_to_google() -> dict:
    """Sistemdeki tüm aktif duruşmaları Google Takvim'e tek yönlü aktarır."""
    service, cal_id = get_calendar_service()
    if service is None or not cal_id:
        return {"success": False, "error": "Google Takvim API ayarları eksik veya kapalı."}

    hearings = Hearing.objects.exclude(status=HearingStatus.CANCELLED).order_by("starts_at")
    total = hearings.count()
    synced = 0
    errors = 0

    for h in hearings:
        event_id = sync_hearing_to_google(h)
        if event_id:
            synced += 1
        else:
            errors += 1

    return {
        "success": True,
        "total": total,
        "synced": synced,
        "errors": errors,
    }


def retry_pending_google_syncs(limit: int = 200, min_age_seconds: int = 0) -> dict:
    """Eşitlemesi başarısız olmuş duruşmaları yeniden dener (iptaller Google'dan silinir).

    `min_age_seconds`: bu süreden yeni değişen kayıtlar atlanır; arka plan işi hâlâ çalışıyor
    olabilir ve aynı duruşma için ikinci bir etkinlik açılmamalıdır.
    """
    service, cal_id = get_calendar_service()
    if service is None or not cal_id:
        return {"success": False, "error": "Google Takvim API ayarları eksik veya kapalı."}
    queryset = Hearing.objects.filter(google_sync_pending=True)
    if min_age_seconds:
        queryset = queryset.filter(
            updated_at__lt=timezone.now() - dt.timedelta(seconds=min_age_seconds)
        )
    pending = list(queryset.order_by("starts_at")[:limit])
    synced = errors = 0
    for hearing in pending:
        sync_hearing_to_google(hearing)
        if hearing.google_sync_pending:
            errors += 1
        else:
            synced += 1
    return {"success": True, "total": len(pending), "synced": synced, "errors": errors}


def test_google_calendar_connection(office: OfficeSettings | None = None) -> tuple[bool, str]:
    """Google Takvim API bağlantısını test eder: (başarılı_mı, mesaj) döndürür."""
    if office is None:
        office = OfficeSettings.load()

    cal_id = (office.google_calendar_id or "").strip()
    raw_json = (office.google_service_account_json or "").strip()

    if not cal_id:
        return False, "Google Takvim ID tanımlanmamış."
    if not raw_json:
        return False, "Google Service Account JSON anahtarı girilmemiş."

    service, cal_id = get_calendar_service(office, require_enabled=False)
    if service is None:
        return False, "Google Calendar servisi başlatılamadı. JSON anahtarını kontrol edin."

    from googleapiclient.errors import HttpError

    try:
        service.events().list(calendarId=cal_id, maxResults=1).execute()
        return True, "Google Takvim bağlantısı başarılı; etkinlikler okunabiliyor."
    except HttpError as e:
        status = getattr(e, "status_code", None) or getattr(e, "resp", {}).status
        if status == 404:
            return (
                False,
                f"Takvim bulunamadı (404). '{cal_id}' ID'sinin doğruluğunu ve "
                "takvimin Service Account e-postasıyla paylaşıldığını kontrol edin.",
            )
        if status == 403:
            return (
                False,
                "Erişim yetkisi yetersiz (403). Google Takvim > Ayarlar > "
                "'Belirli kişilerle paylaş' bölümünden Service Account e-postasına "
                "'Etkinliklerde değişiklik yapma' izni verin.",
            )
        return False, f"Google API Hatası ({status}): {e}"
    except Exception as e:
        return False, f"Bağlantı sırasında beklenmeyen bir hata oluştu: {e}"
