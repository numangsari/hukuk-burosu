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

from django.utils import timezone

from apps.cases.models import Hearing, HearingStatus
from apps.office.models import OfficeSettings

log = logging.getLogger(__name__)


def get_calendar_service(office: OfficeSettings | None = None):
    """Google Calendar v3 API istemcisini döndürür; ayar yoksa None döner."""
    if office is None:
        office = OfficeSettings.load()

    if not office.google_calendar_api_enabled:
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
    kind_label = hearing.get_kind_display()
    title = hearing.title_display
    summary = f"[{kind_label}] {title}"

    lines = []
    if hearing.case:
        lines.append(f"Dosya: {hearing.case.display_name}")
        lines.append(f"Esas/No: {hearing.case.official_no or '—'}")
    if hearing.client:
        lines.append(f"Müvekkil: {hearing.client}")
    if hearing.assigned_to:
        lines.append(f"Sorumlu / Görevli: {hearing.assigned_to}")
    elif hearing.case and hearing.case.responsible_lawyer:
        lines.append(f"Sorumlu Avukat: {hearing.case.responsible_lawyer}")

    if hearing.notes:
        lines.append(f"\nNotlar:\n{hearing.notes}")
    if hearing.result:
        lines.append(f"\nSonuç / Kararlar:\n{hearing.result}")
    if hearing.portal_ref:
        lines.append(f"\nUYAP Ref: {hearing.portal_ref}")

    lines.append("\n(Bu etkinlik Özkurt Hukuk Otomasyonu tarafından oluşturulmuştur.)")

    description = "\n".join(lines)

    location_parts = []
    if hearing.authority:
        location_parts.append(hearing.authority)
    elif hearing.case and hearing.case.authority:
        location_parts.append(hearing.case.authority)
    if hearing.room:
        location_parts.append(f"Salon: {hearing.room}")
    location = " — ".join(location_parts)

    starts_at = timezone.localtime(hearing.starts_at)
    if hearing.ends_at:
        ends_at = timezone.localtime(hearing.ends_at)
    else:
        ends_at = starts_at + dt.timedelta(minutes=30)

    tz_str = "Europe/Istanbul"
    return {
        "summary": summary,
        "description": description,
        "location": location,
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


def sync_hearing_to_google(hearing: Hearing) -> str | None:
    """Tek bir duruşmayı Google Takvim'e tek yönlü yazar veya günceller."""
    service, cal_id = get_calendar_service()
    if service is None or not cal_id:
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
                log.info("Google takvim etkinliği silinirken hata (zaten silinmiş olabilir): %s", e)
            hearing.google_event_id = ""
            hearing.save(update_fields=["google_event_id"])
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
        return event_id
    except Exception as e:
        log.warning("Google Takvim senkronizasyon hatası (Hearing #%s): %s", hearing.pk, e)
        return None


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
