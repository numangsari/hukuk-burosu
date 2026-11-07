from django import template

from apps.imports.portal_status import portal_indicator

register = template.Library()


@register.inclusion_tag("imports/_portal_indicator.html", takes_context=True)
def portal_status(context):
    request = context["request"]
    return portal_indicator(request.user)
