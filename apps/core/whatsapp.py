"""WhatsApp Click-to-Chat (wa.me) yardımcıları ve mesaj şablonları."""

import urllib.parse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.cases.models import Case, Hearing


def clean_phone_for_whatsapp(value: Any) -> str:
    """Telefon numarasını WhatsApp 'wa.me' formatına çevirir.

    Örnekler:
      '0532 123 45 67'     -> '905321234567'
      '+90 (532) 123 4567' -> '905321234567'
      '5321234567'         -> '905321234567'
      '0212 234 56 78'     -> '902122345678'
      '+49 170 1234567'    -> '491701234567'
      '0049 170 1234567'   -> '491701234567'
    """
    if not value:
        return ""
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return ""

    if digits.startswith("00"):
        digits = digits[2:]

    # Türkiye yerel formatları
    if len(digits) == 11 and digits.startswith("0"):
        digits = "90" + digits[1:]
    elif len(digits) == 10 and digits[0] in "23458":
        digits = "90" + digits

    # Uluslararası numara en az 8, en fazla 15 rakam olmalıdır
    if 8 <= len(digits) <= 15:
        return digits
    return ""


def build_whatsapp_url(phone: Any, message: str = "") -> str:
    """Belirtilen numara ve mesaj için masaüstü WhatsApp URI'si oluşturur."""
    cleaned = clean_phone_for_whatsapp(phone)
    if not cleaned:
        return ""
    url = f"whatsapp://send?phone={cleaned}"
    if message:
        url += f"&text={urllib.parse.quote(message.strip())}"
    return url


def format_hearing_result_message(
    hearing: "Hearing",
    next_hearing_dt: str | None = None,
    decisions: str | None = None,
    office_name: str | None = None,
) -> str:
    """Duruşma sonucu için müvekkil bilgilendirme şablonu üretir."""
    from apps.office.models import OfficeSettings

    office = office_name or OfficeSettings.load().name
    client = getattr(hearing, "effective_client", None)
    if not client:
        client = hearing.client or (hearing.case.client if hearing.case else None)
    client_name = client.name if client else "Müvekkilimiz"
    case_ref = hearing.case.display_name if hearing.case else (hearing.title or "Dosyanız")
    authority = hearing.authority or (hearing.case.authority if hearing.case else "")

    lines = [f"Sayın {client_name},"]
    if authority:
        lines.append(
            f"{authority} nezdindeki {case_ref} sayılı dosyanızın bugünkü celsesi tamamlanmıştır."
        )
    else:
        lines.append(f"{case_ref} sayılı dosyanızın bugünkü celsesi tamamlanmıştır.")

    dec = (decisions or hearing.decisions or hearing.result or "").strip()
    if dec:
        lines.append(f"Duruşmada Verilen Karar / Sonuç:\n{dec}")

    if next_hearing_dt:
        lines.append(f"Bir Sonraki Duruşma Günü: {next_hearing_dt}")

    lines.append(f"Bilgilerinize sunarız.\n{office}")
    return "\n\n".join(lines)


def format_hearing_reminder_message(
    hearing: "Hearing",
    office_name: str | None = None,
) -> str:
    """Yaklaşan duruşma için müvekkil hatırlatma şablonu üretir."""
    from apps.office.models import OfficeSettings

    office = office_name or OfficeSettings.load().name
    client = getattr(hearing, "effective_client", None)
    if not client:
        client = hearing.client or (hearing.case.client if hearing.case else None)
    client_name = client.name if client else "Müvekkilimiz"
    case_ref = hearing.case.display_name if hearing.case else (hearing.title or "Dosyanız")
    authority = hearing.authority or (hearing.case.authority if hearing.case else "")
    dt_str = hearing.starts_at.strftime("%d.%m.%Y saat %H:%M")

    lines = [f"Sayın {client_name},"]
    if authority:
        lines.append(f"{authority} {case_ref} sayılı dosyanızın duruşması {dt_str} tarihindedir.")
    else:
        lines.append(f"{case_ref} sayılı dosyanızın duruşması {dt_str} tarihindedir.")

    details = []
    if hearing.room:
        details.append(f"Salon: {hearing.room}")
    if hearing.is_remote:
        details.append("E-duruşma olarak icra edilecektir.")
    if details:
        lines.append(" · ".join(details))

    lines.append(f"Bilgilerinize sunarız.\n{office}")
    return "\n\n".join(lines)


def format_case_info_message(case: "Case", office_name: str | None = None) -> str:
    """Dosya hakkında genel bilgilendirme şablonu üretir."""
    from apps.office.models import OfficeSettings

    office = office_name or OfficeSettings.load().name
    client_name = case.client.name if case.client else "Müvekkilimiz"
    return (
        f"Sayın {client_name},\n\n"
        f"{case.display_name} sayılı dosyanız ile ilgili olarak bilgi vermek amacıyla "
        f"iletişime geçiyoruz.\n\n"
        f"Bilgilerinize sunarız.\n{office}"
    )


def get_hearing_wa_templates(hearing: "Hearing", office_name: str | None = None) -> dict[str, str]:
    """Bir duruşma için kullanılabilecek hazır WhatsApp şablonları sözlüğü döner."""
    templates: dict[str, str] = {}
    is_held_or_has_result = (
        hearing.status in ("held", "postponed") or bool(hearing.result) or bool(hearing.decisions)
    )

    if is_held_or_has_result:
        templates["Duruşma Sonucu"] = format_hearing_result_message(
            hearing, office_name=office_name
        )
        templates["Duruşma Hatırlatması"] = format_hearing_reminder_message(
            hearing, office_name=office_name
        )
    else:
        templates["Duruşma Hatırlatması"] = format_hearing_reminder_message(
            hearing, office_name=office_name
        )
        templates["Duruşma Sonucu"] = format_hearing_result_message(
            hearing, office_name=office_name
        )

    return templates


def get_case_wa_templates(case: "Case", office_name: str | None = None) -> dict[str, str]:
    """Bir dosya için kullanılabilecek hazır WhatsApp şablonları sözlüğü döner."""
    from apps.office.models import OfficeSettings

    office = office_name or OfficeSettings.load().name
    client_name = case.client.name if case.client else "Müvekkilimiz"

    adv_text = (
        f"Sayın {client_name},\n\n"
        f"{case.display_name} sayılı dosyanızın dava ve takip masrafları için "
        f"masraf avansı yatırılması gerekmektedir. Hesap bilgileri için büromuzla "
        f"iletişime geçmenizi rica ederiz.\n\n"
        f"İyi çalışmalar dileriz.\n{office}"
    )
    return {
        "Dosya Bilgilendirmesi": format_case_info_message(case, office_name=office),
        "Masraf / Avans Talebi": adv_text,
    }
