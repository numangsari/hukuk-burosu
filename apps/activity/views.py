import datetime as dt
import json

from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.views.generic import ListView

from apps.accounts.models import User
from apps.core.pagination import page_size
from apps.core.permissions import is_admin

ACTION_LABELS = {
    LogEntry.Action.CREATE: ("oluşturdu", "success"),
    LogEntry.Action.UPDATE: ("güncelledi", "primary"),
    LogEntry.Action.DELETE: ("sildi", "danger"),
    LogEntry.Action.ACCESS: ("oturum", "info"),
}

# Aktivite ekranında süzülebilen kayıt türleri
TRACKED = [
    ("clients", "client"),
    ("clients", "powerofattorney"),
    ("clients", "party"),
    ("cases", "case"),
    ("cases", "document"),
    ("cases", "hearing"),
    ("tasks", "task"),
    ("accounting", "ledgerentry"),
    ("accounts", "user"),
]


def _date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def decorate(entries):
    """Şablon için: işlem etiketi, kayıt türü adı, kayda bağlantı ve okunur değişiklikler."""
    for e in entries:
        e.label, e.tone = ACTION_LABELS.get(e.action, ("", ""))
        raw = e.changes
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = {}
        e.event = raw.get("olay", "") if isinstance(raw, dict) else ""
        model = e.content_type.model_class()
        e.type_name = model._meta.verbose_name if model else e.content_type.model
        e.link = ""
        if e.action != LogEntry.Action.DELETE and model and hasattr(model, "get_absolute_url"):
            obj = model.objects.filter(pk=e.object_pk).first()
            e.link = obj.get_absolute_url() if obj else ""
        try:
            e.display_changes = e.changes_display_dict if e.action == LogEntry.Action.UPDATE else {}
        except Exception:  # bozuk/eski kayıt alanları ekranı kırmasın
            e.display_changes = {}
    return entries


def history_for(obj, limit=50):
    return decorate(
        list(LogEntry.objects.get_for_object(obj).select_related("actor", "content_type")[:limit])
    )


class ActivityListView(ListView):
    """Yönetici herkesin, diğer kullanıcılar yalnızca kendi işlemlerini görür."""

    template_name = "activity/list.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_paginate_by(self, queryset):
        return page_size(self.request, default=50)

    def get_queryset(self):
        g, u = self.request.GET, self.request.user
        qs = LogEntry.objects.select_related("actor", "content_type").order_by("-timestamp")
        if is_admin(u):
            if actor := g.get("kullanici"):
                qs = qs.filter(actor_id=actor)
        else:
            qs = qs.filter(actor=u)
        if t := g.get("tur"):
            qs = qs.filter(content_type_id=t)
        if (a := g.get("islem")) and a.isdigit():
            qs = qs.filter(action=int(a))
        if start := _date(g.get("baslangic")):
            qs = qs.filter(timestamp__date__gte=start)
        if end := _date(g.get("bitis")):
            qs = qs.filter(timestamp__date__lte=end)
        if q := (g.get("q") or "").strip():
            qs = qs.filter(object_repr__icontains=q)
        return qs

    def get_template_names(self):
        if self.request.htmx and not self.request.htmx.boosted:
            return ["activity/_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        decorate(ctx["entries"])
        cts = [ContentType.objects.get_by_natural_key(a, m) for a, m in TRACKED]
        ctx.update(
            users=User.objects.all() if is_admin(self.request.user) else [],
            types=[(ct.pk, ct.model_class()._meta.verbose_name_plural) for ct in cts],
            actions=[(k, v[0]) for k, v in ACTION_LABELS.items()],
        )
        return ctx
