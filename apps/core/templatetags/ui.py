import html
import json
from decimal import Decimal

from django import template
from django.utils.http import urlencode
from django.utils.safestring import mark_safe

from apps.core.links import OFFICE_LINKS
from apps.core.whatsapp import (
    build_whatsapp_url,
    clean_phone_for_whatsapp,
    get_case_wa_templates,
    get_hearing_wa_templates,
)

register = template.Library()


@register.simple_tag
def office_links():
    return OFFICE_LINKS


@register.filter
def tl(value):
    """Tutarı Türk formatında gösterir: 1.234,50 ₺"""
    if value in (None, ""):
        return "—"
    q = Decimal(value).quantize(Decimal("0.01"))
    sign = "-" if q < 0 else ""
    whole, frac = f"{abs(q):.2f}".split(".")
    whole = f"{int(whole):,}".replace(",", ".")
    return f"{sign}{whole},{frac} ₺"


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if hasattr(mapping, "get") else None


@register.filter
def phone_tr(value):
    """05330430023 -> 0533 043 00 23. Tanınmayan biçim olduğu gibi döner."""
    digits = "".join(c for c in str(value or "") if c.isdigit())
    if len(digits) == 10 and not digits.startswith("0"):
        digits = "0" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return f"{digits[:4]} {digits[4:7]} {digits[7:9]} {digits[9:]}"
    return value


@register.simple_tag(takes_context=True)
def query_with(context, **kwargs):
    """Mevcut GET parametrelerini koruyarak bazılarını değiştirir."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return "?" + urlencode(params, doseq=True)


@register.simple_tag(takes_context=True)
def sort_link(context, field, label):
    current = context["request"].GET.get("sort", "")
    if current == field:
        new, icon = f"-{field}", " ▲"
    elif current == f"-{field}":
        new, icon = field, " ▼"
    else:
        new, icon = field, ""
    url = query_with(context, sort=new, page=None)
    from django.utils.html import format_html

    return format_html(
        '<a href="{}" class="text-reset text-decoration-none">{}{}</a>', url, label, icon
    )


@register.simple_tag
def page_numbers(page_obj):
    if not page_obj:
        return []
    return page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)


@register.filter
def clean_wa_phone(value):
    """WhatsApp için temizlenmiş uluslararası numara döner."""
    return clean_phone_for_whatsapp(value)


@register.simple_tag
def wa_url(phone, text=""):
    """WhatsApp wa.me bağlantısı üretir."""
    return build_whatsapp_url(phone, message=text)


@register.filter
def json_attr(value):
    """HTML data-* niteliklerinde güvenle kullanmak için JSON verisini escape eder."""
    if value is None:
        return ""
    if isinstance(value, str):
        return mark_safe(html.escape(value, quote=True))
    dumped = json.dumps(value, ensure_ascii=False)
    return mark_safe(html.escape(dumped, quote=True))


@register.simple_tag
def hearing_wa_templates(hearing):
    """Duruşma için hazır şablonlar sözlüğü üretir."""
    if not hearing:
        return {}
    return get_hearing_wa_templates(hearing)


@register.simple_tag
def case_wa_templates(case):
    """Dosya için hazır şablonlar sözlüğü üretir."""
    if not case:
        return {}
    return get_case_wa_templates(case)
