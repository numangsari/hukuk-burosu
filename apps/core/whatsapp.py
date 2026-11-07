"""WhatsApp Click-to-Chat (wa.me) yardımcıları ve mesaj şablonları."""

import urllib.parse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.cases.models import Case, Hearing
    from apps.clients.models import Client


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

    lines = [f"Sayın {client_name},"]
    if hearing.case:
        if hearing.case.authority:
            case_label = hearing.case.display_name
        elif hearing.authority:
            no_disp = hearing.case.official_no_display or hearing.case.display_name
            case_label = f"{hearing.authority} {no_disp}".strip()
        else:
            case_label = hearing.case.display_name
        lines.append(f"{case_label} sayılı dosyanızın bugünkü celsesi tamamlanmıştır.")
    elif hearing.authority:
        title = hearing.title or "Duruşmanız"
        lines.append(f"{hearing.authority} nezdindeki {title} tamamlanmıştır.")
    else:
        title = hearing.title or "Dosyanızın duruşması"
        lines.append(f"{title} tamamlanmıştır.")

    if hearing.excuse_submitted:
        lines.append("Not: Bu celse için mahkemeye mazeret dilekçesi sunulmuştur.")

    dec = (decisions or hearing.decisions or hearing.result or "").strip()
    if dec:
        lines.append(f"Duruşmada Verilen Karar / Sonuç:\n{dec}")

    # Sonraki duruşma parametre olarak verilmediyse ve dosyada varsa otomatik getir
    if not next_hearing_dt and hearing.case:
        next_h = (
            hearing.case.hearings.filter(starts_at__gt=hearing.starts_at)
            .order_by("starts_at")
            .first()
        )
        if next_h:
            next_hearing_dt = next_h.starts_at.strftime("%d.%m.%Y saat %H:%M")

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
    dt_str = hearing.starts_at.strftime("%d.%m.%Y saat %H:%M")

    lines = [f"Sayın {client_name},"]
    if hearing.case:
        if hearing.case.authority:
            case_label = hearing.case.display_name
        elif hearing.authority:
            no_disp = hearing.case.official_no_display or hearing.case.display_name
            case_label = f"{hearing.authority} {no_disp}".strip()
        else:
            case_label = hearing.case.display_name
        lines.append(f"{case_label} sayılı dosyanızın duruşması {dt_str} tarihindedir.")
    elif hearing.authority:
        title = hearing.title or "Duruşmanız"
        lines.append(f"{hearing.authority} {title} {dt_str} tarihindedir.")
    else:
        title = hearing.title or "Duruşmanız"
        lines.append(f"{title} {dt_str} tarihindedir.")

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


def _bank_details() -> str:
    from apps.office.models import OfficeSettings

    return (OfficeSettings.load().bank_details or "").strip()


def get_case_wa_templates(case: "Case", office_name: str | None = None) -> dict[str, str]:
    """Bir dosya için kullanılabilecek hazır WhatsApp şablonları sözlüğü döner."""
    from apps.office.models import OfficeSettings

    office = office_name or OfficeSettings.load().name
    client_name = case.client.name if case.client else "Müvekkilimiz"
    bank = _bank_details()
    if bank:
        account_text = (
            f"Hesap bilgilerimiz aşağıdadır:\n\n{bank}\n\n"
            f"Açıklama kısmına dosya numarasını ({case.display_name}) yazmanızı rica ederiz.\n\n"
        )
    else:
        account_text = "Hesap bilgileri için büromuzla iletişime geçmenizi rica ederiz.\n\n"

    adv_text = (
        f"Sayın {client_name},\n\n"
        f"{case.display_name} sayılı dosyanızın dava ve takip masrafları için "
        f"masraf avansı yatırılması gerekmektedir. {account_text}"
        f"İyi çalışmalar dileriz.\n{office}"
    )
    templates = {
        "Dosya Bilgilendirmesi": format_case_info_message(case, office_name=office),
        "Masraf / Avans Talebi": adv_text,
    }
    if bank:
        templates["Banka Bilgileri"] = (
            f"Sayın {client_name},\n\n"
            f"{case.display_name} sayılı dosyanız için ödeme yapacağınız hesap bilgileri:\n\n"
            f"{bank}\n\n"
            f"Açıklama kısmına dosya numarasını yazmanızı rica ederiz.\n\n"
            f"İyi çalışmalar dileriz.\n{office}"
        )
    return templates


def get_client_wa_templates(client: "Client", office_name: str | None = None) -> dict[str, str]:
    """Müvekkil kartı için hazır WhatsApp şablonları sözlüğü döner."""
    from apps.office.models import OfficeSettings

    office = office_name or OfficeSettings.load().name
    client_name = client.name if client else "Müvekkilimiz"

    bank = _bank_details()
    if bank:
        advance = (
            f"Sayın {client_name},\n\n"
            f"Dosya ve takip masrafları avansı ödemesi için hesap bilgilerimiz aşağıdadır:\n\n"
            f"{bank}\n\n"
            f"İyi çalışmalar dileriz.\n{office}"
        )
    else:
        advance = (
            f"Sayın {client_name},\n\n"
            f"Dosya ve takip masrafları avansı ödemesi için "
            f"büromuzla iletişime geçmenizi rica ederiz.\n\n"
            f"İyi çalışmalar dileriz.\n{office}"
        )
    templates = {
        "Genel İletişim": (f"Sayın {client_name},\n\n\n\nBilgilerinize sunarız.\n{office}"),
        "Masraf / Avans Bilgisi": advance,
    }
    if bank:
        templates["Banka Bilgileri"] = (
            f"Sayın {client_name},\n\n"
            f"Ödeme yapacağınız büro hesap bilgileri:\n\n"
            f"{bank}\n\n"
            f"İyi çalışmalar dileriz.\n{office}"
        )
    return templates
