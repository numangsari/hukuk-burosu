from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View

from apps.core.permissions import AdminRequiredMixin

from .models import BackupRecord
from .services import run_backup


class BackupNowView(AdminRequiredMixin, View):
    def post(self, request):
        rec = run_backup(BackupRecord.Kind.MANUAL)
        if rec.status == BackupRecord.Status.OK:
            messages.success(request, f"Yedek alındı: {rec.file_name}")
            if rec.message:
                messages.warning(request, rec.message)
        else:
            messages.error(request, f"Yedek alınamadı: {rec.message}")
        return redirect(f"{reverse('accounts:settings')}?bolum=yedek")
