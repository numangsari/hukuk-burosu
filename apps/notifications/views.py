from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import Notification


class NotificationListView(View):
    """Zil menüsü içeriği (HTMX ile yüklenir)."""

    def get(self, request):
        items = request.user.notifications.all()[:15]
        return render(request, "notifications/_list.html", {"items": items})


class NotificationOpenView(View):
    def get(self, request, pk):
        n = get_object_or_404(Notification, pk=pk, user=request.user)
        if not n.is_read:
            n.is_read = True
            n.save(update_fields=["is_read"])
        return redirect(n.url or "core:home")


class NotificationReadAllView(View):
    def post(self, request):
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return render(
            request, "notifications/_list.html", {"items": request.user.notifications.all()[:15]}
        )
