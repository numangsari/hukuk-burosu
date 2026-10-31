from decimal import Decimal

from django import template
from django.utils.http import urlencode

register = template.Library()


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
